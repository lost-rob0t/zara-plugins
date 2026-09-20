import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertError
from zara_expert.lisp_family import lisp_family_specs, registered_predicates
from zara_expert.lisp_source_contract import validate_lisp_source_contracts
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


def _adapter_ready_source(path: Path, key: str, *, policy: bool = True) -> Path:
    specs = {spec.key: spec for spec in lisp_family_specs()}
    spec = specs[key]
    exports = [
        "expert_id/1",
        "upstream_contract/1",
        *(f"{predicate}/{arity}" for predicate, arity in registered_predicates().items()),
        "provider_policy/1",
        "max_model_calls/1",
        "model_calls/1",
    ]
    module_name = f"fixture_{key.replace('-', '_')}"
    body = f":- module({module_name}, [{', '.join(exports)}]).\n"
    body += f"expert_id('{spec.expert_id}').\n"
    body += f"upstream_contract('{spec.upstream_issue}').\n"
    if policy:
        body += (
            "provider_policy(disabled).\n"
            "max_model_calls(0).\n"
            "model_calls(0).\n"
        )
    path.write_text(body, encoding="utf-8")
    return path


class LispSourceContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_adapter_ready_lisp_family_brains_pass_without_provider_credentials(self):
        sources = {
            key: [_adapter_ready_source(self.root / f"{key}.pl", key)]
            for key in ("lisp", "common-lisp", "emacs-lisp")
        }
        validate_lisp_source_contracts(sources)

    def test_missing_adapter_predicates_fail_closed_before_activation(self):
        source = self.root / "lisp-incomplete.pl"
        source.write_text(
            ":- module(lisp_incomplete, [expert_id/1, upstream_contract/1, "
            "provider_policy/1, max_model_calls/1, model_calls/1]).\n"
            "expert_id('zara:expert/lisp').\n"
            "upstream_contract('lost-rob0t/prolog-rlm#494').\n"
            "provider_policy(disabled).\n"
            "max_model_calls(0).\n"
            "model_calls(0).\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ExpertError, "brain is not adapter-ready") as caught:
            validate_lisp_source_contracts({"lisp": [source]})

        message = str(caught.exception)
        self.assertIn("structural_check/2", message)
        self.assertIn("preview_repair/3", message)
        self.assertIn("verify_repair/3", message)

    def test_zero_model_policy_must_be_declared_by_brain(self):
        source = _adapter_ready_source(
            self.root / "common-lisp-policy.pl",
            "common-lisp",
            policy=False,
        )

        with self.assertRaisesRegex(ExpertError, "does not pin pure-symbolic policy") as caught:
            validate_lisp_source_contracts({"common-lisp": [source]})

        message = str(caught.exception)
        self.assertIn("provider_policy(disabled).", message)
        self.assertIn("max_model_calls(0).", message)
        self.assertIn("model_calls(0).", message)

    def test_wrong_brain_identity_cannot_be_mounted_under_another_namespace(self):
        source = _adapter_ready_source(self.root / "common-lisp.pl", "common-lisp")

        with self.assertRaisesRegex(ExpertError, "identity does not match adapter contract") as caught:
            validate_lisp_source_contracts({"lisp": [source]})

        self.assertIn("expert_id('zara:expert/lisp').", str(caught.exception))

    def test_comments_cannot_spoof_exports_policy_or_identity(self):
        source = self.root / "spoofed.pl"
        source.write_text(
            ":- module(spoofed, [expert_id/1, upstream_contract/1, provider_policy/1, "
            "max_model_calls/1, model_calls/1]).\n"
            "% structural_check/2, preview_repair/3, verify_repair/3\n"
            "% expert_id('zara:expert/lisp'). provider_policy(disabled). max_model_calls(0). model_calls(0).\n"
            "expert_id('zara:expert/not-lisp').\n"
            "upstream_contract('wrong').\n"
            "provider_policy(enabled).\n"
            "max_model_calls(1).\n"
            "model_calls(1).\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ExpertError, "brain is not adapter-ready"):
            validate_lisp_source_contracts({"lisp": [source]})

    def test_plugin_rejects_invalid_lisp_brain_before_symbols_or_backend_calls(self):
        source = self.root / "invalid-lisp.pl"
        source.write_text("% not a canonical brain\n", encoding="utf-8")
        runtime = RecordingRuntime({"lisp_family_sources": {"lisp": [str(source)]}})
        backend = RecordingBackend()
        plugin = ZaraExpertPlugin(backend=backend, state_root=self.root / "state")

        with self.assertRaisesRegex(ExpertError, "brain is not adapter-ready"):
            plugin.start(runtime)

        self.assertEqual(runtime.registrations, [])
        self.assertEqual(backend.calls, [])
        self.assertEqual(plugin._registered_lisp_experts, frozenset())
        self.assertFalse((self.root / "state" / "lisp").exists())


if __name__ == "__main__":
    unittest.main()
