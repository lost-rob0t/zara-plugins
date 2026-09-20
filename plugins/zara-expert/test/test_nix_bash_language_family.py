import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertHost
from zara_expert.language_family import (
    descriptors,
    language_family_specs,
    matching_experts,
    register_language_family,
    registered_predicates,
)
from zara_expert.language_handler import make_language_expert_handler


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def run(self, request):
        self.calls.append(dict(request))
        return {
            "ok": True,
            "results": ["evidence:canonical-language-brain"],
            "trace": ["rule:zero-model"],
        }


class NixBashLanguageFamilyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.backend = RecordingBackend()
        self.host = ExpertHost(self.backend, state_root=self.root / "state")

    def tearDown(self):
        self.temporary.cleanup()

    def _brain(self, name):
        path = self.root / f"{name}.pl"
        exports = [
            *(f"{predicate}/{arity}" for predicate, arity in registered_predicates().items()),
            "provider_policy/1",
            "max_model_calls/1",
            "model_calls/1",
        ]
        path.write_text(
            f":- module({name}_fixture, [{', '.join(exports)}]).\n"
            "provider_policy(disabled).\n"
            "max_model_calls(0).\n"
            "model_calls(0).\n",
            encoding="utf-8",
        )
        return path

    def test_specs_bind_nix_and_bash_to_upstream_contracts(self):
        specs = {spec.key: spec for spec in language_family_specs()}
        self.assertEqual(specs["nix"].expert_id, "zara:expert/nix")
        self.assertEqual(specs["nix"].namespace, "nix-expert")
        self.assertEqual(specs["nix"].upstream_issue, "lost-rob0t/prolog-rlm#503")
        self.assertEqual(specs["bash"].expert_id, "zara:expert/bash")
        self.assertEqual(specs["bash"].namespace, "bash-expert")
        self.assertEqual(specs["bash"].upstream_issue, "lost-rob0t/prolog-rlm#502")
        self.assertEqual(matching_experts("flake.nix"), ("zara:expert/nix",))
        self.assertEqual(matching_experts("bin/run.sh"), ("zara:expert/bash",))
        self.assertEqual(matching_experts("bin/run.bash"), ("zara:expert/bash",))

    def test_optional_descriptors_are_not_advertised_without_sources(self):
        ids = {item["expert_id"] for item in descriptors()}
        self.assertNotIn("zara:expert/nix", ids)
        self.assertNotIn("zara:expert/bash", ids)

    def test_registered_nix_and_bash_publish_available_zero_model_descriptors(self):
        registered = register_language_family(
            self.host,
            {
                "nix": [self._brain("nix")],
                "bash": [self._brain("bash")],
            },
        )
        self.assertEqual(registered, frozenset({"nix", "bash"}))
        items = {item["expert_id"]: item for item in descriptors(registered)}
        for expert_id in ("zara:expert/nix", "zara:expert/bash"):
            with self.subTest(expert_id=expert_id):
                item = items[expert_id]
                self.assertEqual(item["availability"], "available")
                self.assertEqual(item["reasoning_kind"], "symbolic")
                self.assertEqual(item["resource_limits"]["max_model_calls"], 0)
                self.assertEqual(item["fallback_policy"], "fail_closed")

    def test_handlers_use_registered_predicate_host_and_exact_zero_model_ledger(self):
        register_language_family(
            self.host,
            {
                "nix": [self._brain("nix")],
                "bash": [self._brain("bash")],
            },
        )
        cases = (
            ("zara:expert/nix", "{ x = 1; }", "nix-expert"),
            ("zara:expert/bash", "printf '%s\\n' ok", "bash-expert"),
        )
        for expert_id, source, namespace in cases:
            with self.subTest(expert_id=expert_id):
                handler = make_language_expert_handler(self.host, expert_id)
                outcome = handler(
                    expert_operation="inspect",
                    source=source,
                    source_generation="generation-7",
                )
                self.assertEqual(outcome["verdict"], "succeeded")
                self.assertEqual(outcome["usage"], {"model_calls": 0})
                self.assertEqual(outcome["effect_receipts"], [])
                self.assertEqual(outcome["data"]["result"]["model_calls"], 0)
                call = self.backend.calls[-1]
                self.assertEqual(call["namespace"], namespace)
                self.assertEqual(call["capability"].predicate, "language_evidence")
                self.assertNotIn("goal", call)


if __name__ == "__main__":
    unittest.main()
