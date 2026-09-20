import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertError
from zara_expert.language_family import registered_predicates
from zara_expert.language_source_contract import validate_language_source_contracts
from zara_expert.plugin import ZaraExpertPlugin


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def run(self, request):
        self.calls.append(dict(request))
        return {"ok": True, "results": [], "trace": []}


class RecordingRuntime:
    def __init__(self, configuration):
        self.configuration = configuration
        self.registrations = []

    def register_symbol(self, symbol, kind, value, **metadata):
        self.registrations.append((symbol, kind, value, metadata))
        return len(self.registrations)


def _adapter_ready_source(path: Path, *, policy: bool = True) -> Path:
    exports = [
        *(f"{predicate}/{arity}" for predicate, arity in registered_predicates().items()),
        "provider_policy/1",
        "max_model_calls/1",
        "model_calls/1",
    ]
    body = f":- module(adapter_ready, [{', '.join(exports)}]).\n"
    if policy:
        body += (
            "provider_policy(disabled).\n"
            "max_model_calls(0).\n"
            "model_calls(0).\n"
        )
    path.write_text(body, encoding="utf-8")
    return path


class LanguageSourceContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_current_dotfiles_contract_only_brain_cannot_false_green_activation(self):
        source = self.root / "python-expert.pl"
        source.write_text(
            ":- module(dotfiles_python_expert, [\n"
            "    expert_id/1, upstream_contract/1, accepts_extension/1,\n"
            "    supports_semantic/1, evidence_role/2, generation_current/2,\n"
            "    repair_verification/1, provider_policy/1,\n"
            "    max_model_calls/1, model_calls/1\n"
            "]).\n"
            "provider_policy(disabled).\n"
            "max_model_calls(0).\n"
            "model_calls(0).\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ExpertError, "brain is not adapter-ready") as caught:
            validate_language_source_contracts({"python": [source]})

        message = str(caught.exception)
        self.assertIn("language_applicable/3", message)
        self.assertIn("language_evidence/3", message)
        self.assertIn("language_style_rules/3", message)

    def test_zero_model_policy_must_be_declared_by_canonical_brain(self):
        source = _adapter_ready_source(self.root / "nim-expert.pl", policy=False)

        with self.assertRaisesRegex(ExpertError, "does not pin pure-symbolic policy") as caught:
            validate_language_source_contracts({"nim": [source]})

        message = str(caught.exception)
        self.assertIn("provider_policy(disabled).", message)
        self.assertIn("max_model_calls(0).", message)
        self.assertIn("model_calls(0).", message)

    def test_comments_cannot_spoof_required_exports_or_zero_model_policy(self):
        source = self.root / "spoofed.pl"
        source.write_text(
            ":- module(spoofed, [provider_policy/1, max_model_calls/1, model_calls/1]).\n"
            "% language_applicable/3, language_evidence/3, language_style_rules/3\n"
            "% provider_policy(disabled). max_model_calls(0). model_calls(0).\n"
            "provider_policy(enabled).\n"
            "max_model_calls(1).\n"
            "model_calls(1).\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ExpertError, "brain is not adapter-ready"):
            validate_language_source_contracts({"prolog": [source]})

    def test_adapter_ready_brain_passes_preflight_without_provider_credentials(self):
        source = _adapter_ready_source(self.root / "prolog-expert.pl")
        validate_language_source_contracts({"prolog": [source]})

    def test_plugin_fails_before_publishing_incomplete_brain(self):
        source = self.root / "contract-only.pl"
        source.write_text(
            ":- module(contract_only, [provider_policy/1, max_model_calls/1, model_calls/1]).\n"
            "provider_policy(disabled).\n"
            "max_model_calls(0).\n"
            "model_calls(0).\n",
            encoding="utf-8",
        )
        runtime = RecordingRuntime(
            {"language_expert_sources": {"python": [str(source)]}}
        )
        backend = RecordingBackend()
        plugin = ZaraExpertPlugin(
            backend=backend,
            state_root=self.root / "state",
        )

        with self.assertRaisesRegex(ExpertError, "brain is not adapter-ready"):
            plugin.start(runtime)

        self.assertEqual(runtime.registrations, [])
        self.assertEqual(backend.calls, [])
        self.assertEqual(plugin._registered_language_experts, frozenset())


if __name__ == "__main__":
    unittest.main()
