import inspect
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertError, ExpertHost
from zara_expert.language_family import register_language_family
from zara_expert.language_handler import make_language_expert_handler
from zara_expert.plugin import ZaraExpertPlugin


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def run(self, request):
        self.calls.append(dict(request))
        return {
            "ok": True,
            "results": ["evidence:language"],
            "trace": ["rule:language"],
        }


class LanguageHandlerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.backend = RecordingBackend()
        self.host = ExpertHost(self.backend, state_root=self.root / "state")

    def tearDown(self):
        self.temporary.cleanup()

    def _brain(self, name):
        path = self.root / f"{name}.pl"
        path.write_text("% canonical-language-brain-fixture\n", encoding="utf-8")
        return path

    def test_core_handler_uses_host_owned_operation_and_exact_zero_model_ledger(self):
        register_language_family(self.host, {"python": [self._brain("python")]})
        handler = make_language_expert_handler(self.host, "zara:expert/python")

        signature = inspect.signature(handler)
        operation_parameter = signature.parameters["expert_operation"]
        self.assertEqual(operation_parameter.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(operation_parameter.default, inspect.Parameter.empty)

        outcome = handler(
            expert_operation="inspect",
            arguments=["print('ok')", "generation-1", {"var": "Evidence"}],
        )

        self.assertEqual(outcome["verdict"], "succeeded")
        self.assertEqual(outcome["usage"], {"model_calls": 0})
        self.assertEqual(outcome["effect_receipts"], [])
        self.assertEqual(outcome["data"]["result"]["model_calls"], 0)
        self.assertEqual(
            outcome["data"]["result"]["evidence"],
            ["evidence:language"],
        )
        self.assertEqual(
            self.backend.calls[-1]["capability"].predicate,
            "language_evidence",
        )

    def test_core_handler_blocks_repair_apply_before_backend_effects(self):
        handler = make_language_expert_handler(self.host, "zara:expert/nim")

        outcome = handler(
            expert_operation="repair.apply",
            repair={"kind": "replace", "text": "discard"},
            expected_preimage="sha256:fixture",
            source_generation="buffer:7",
        )

        self.assertEqual(outcome["verdict"], "blocked")
        self.assertEqual(outcome["usage"], {"model_calls": 0})
        self.assertEqual(outcome["effect_receipts"], [])
        self.assertEqual(outcome["data"]["reason"], "canonical-typed-edit-required")
        self.assertEqual(self.backend.calls, [])

    def test_effect_fields_fail_closed_outside_repair_apply(self):
        register_language_family(self.host, {"prolog": [self._brain("prolog")]})
        handler = make_language_expert_handler(self.host, "zara:expert/prolog")

        with self.assertRaisesRegex(ExpertError, "repair effect fields"):
            handler(
                expert_operation="inspect",
                arguments=["fact(a).", "generation-1", {"var": "Evidence"}],
                expected_preimage="sha256:must-not-cross",
            )
        self.assertEqual(self.backend.calls, [])

    def test_unknown_expert_fails_closed(self):
        with self.assertRaisesRegex(ExpertError, "unknown language expert"):
            make_language_expert_handler(self.host, "zara:expert/rust")
        self.assertEqual(self.backend.calls, [])

    def test_plugin_exposes_handler_without_parallel_structured_tool(self):
        plugin = ZaraExpertPlugin(
            backend=self.backend,
            state_root=self.root / "plugin-state",
        )
        handler = plugin.language_expert_handler("zara:expert/python")
        self.assertIn("expert_operation", inspect.signature(handler).parameters)
        names = {tool.name for tool in plugin.tools()}
        self.assertNotIn("expert.language_invoke", names)
        self.assertNotIn("expert.language_handler", names)


if __name__ == "__main__":
    unittest.main()
