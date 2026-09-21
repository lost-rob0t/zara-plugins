import inspect
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertError, ExpertHost
from zara_expert.language_family import descriptors, register_language_family
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


class NoEvidenceBackend:
    def __init__(self):
        self.calls = []

    def run(self, request):
        self.calls.append(dict(request))
        return {"ok": True, "results": [], "trace": []}


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
            source="print('ok')",
            source_generation="generation-1",
        )

        self.assertEqual(outcome["verdict"], "succeeded")
        self.assertEqual(outcome["usage"], {"model_calls": 0})
        self.assertEqual(outcome["effect_receipts"], [])
        self.assertEqual(len(outcome["evidence_refs"]), 1)
        self.assertTrue(
            outcome["evidence_refs"][0].startswith("evidence:language:sha256:")
        )
        self.assertLessEqual(len(outcome["evidence_refs"][0]), 128)
        self.assertEqual(outcome["data"]["result"]["model_calls"], 0)
        self.assertEqual(
            outcome["data"]["result"]["evidence"],
            ["evidence:language"],
        )
        call = self.backend.calls[-1]
        self.assertEqual(call["capability"].predicate, "language_evidence")
        self.assertEqual(
            call["arguments"],
            ["print('ok')", "generation-1", {"var": "Result"}],
        )

    def test_missing_symbolic_evidence_is_unknown_not_false_success(self):
        backend = NoEvidenceBackend()
        host = ExpertHost(backend, state_root=self.root / "no-evidence-state")
        register_language_family(host, {"prolog": [self._brain("prolog-no-evidence")]})
        handler = make_language_expert_handler(host, "zara:expert/prolog")

        outcome = handler(
            expert_operation="inspect",
            source="fact(a).",
            source_generation="generation-none",
        )

        self.assertEqual(outcome["verdict"], "unknown")
        self.assertEqual(outcome["usage"], {"model_calls": 0})
        self.assertEqual(outcome["effect_receipts"], [])
        self.assertEqual(outcome["evidence_refs"], [])
        self.assertEqual(outcome["data"], {})
        self.assertEqual(len(backend.calls), 1)

    def test_style_rules_preserve_project_style_and_private_result_variable(self):
        register_language_family(self.host, {"nim": [self._brain("nim-style")]})
        handler = make_language_expert_handler(self.host, "zara:expert/nim")

        outcome = handler(
            expert_operation="style.rules",
            source="proc main() = discard",
            project_style="style:project-v3",
        )

        self.assertEqual(outcome["usage"], {"model_calls": 0})
        call = self.backend.calls[-1]
        self.assertEqual(call["capability"].predicate, "language_style_rules")
        self.assertEqual(
            call["arguments"],
            ["proc main() = discard", "style:project-v3", {"var": "Result"}],
        )

    def test_every_descriptor_operation_binds_to_core_handler_shape(self):
        for item in descriptors({"prolog", "python", "nim"}):
            handler = make_language_expert_handler(self.host, item["expert_id"])
            signature = inspect.signature(handler)
            self.assertIn("expert_operation", signature.parameters)
            for operation in item["operations"]:
                payload = {
                    field["name"]: None
                    for field in operation["input_schema"]["fields"]
                }
                with self.subTest(
                    expert=item["expert_id"],
                    operation=operation["operation_id"],
                ):
                    signature.bind(
                        expert_operation=operation["operation_id"],
                        **payload,
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

    def test_undeclared_effect_field_fails_closed_before_backend(self):
        register_language_family(self.host, {"prolog": [self._brain("prolog")]})
        handler = make_language_expert_handler(self.host, "zara:expert/prolog")

        with self.assertRaisesRegex(ExpertError, "unknown input field"):
            handler(
                expert_operation="inspect",
                source="fact(a).",
                source_generation="generation-1",
                expected_preimage="sha256:must-not-cross",
            )
        self.assertEqual(self.backend.calls, [])

    def test_missing_required_input_fails_closed_before_backend(self):
        register_language_family(self.host, {"python": [self._brain("python-missing")]})
        handler = make_language_expert_handler(self.host, "zara:expert/python")

        with self.assertRaisesRegex(ExpertError, "missing required input field"):
            handler(
                expert_operation="inspect",
                source="print('missing generation')",
            )
        self.assertEqual(self.backend.calls, [])

    def test_lane3_malformed_identity_and_operation_shapes_fail_closed_before_backend(self):
        for malformed_expert_id in ([], {}, {"prolog"}):
            with self.subTest(expert_id=repr(malformed_expert_id)):
                with self.assertRaisesRegex(ExpertError, "unknown language expert"):
                    make_language_expert_handler(self.host, malformed_expert_id)
        self.assertEqual(self.backend.calls, [])

        register_language_family(self.host, {"prolog": [self._brain("prolog-shape")]})
        handler = make_language_expert_handler(self.host, "zara:expert/prolog")
        for malformed_operation in ([], {}, {"inspect"}):
            with self.subTest(operation=repr(malformed_operation)):
                with self.assertRaisesRegex(
                    ExpertError,
                    "unsupported language expert operation",
                ):
                    handler(
                        expert_operation=malformed_operation,
                        source="fact(a).",
                        source_generation="generation-shape",
                    )
        self.assertEqual(self.backend.calls, [])

    def test_lane3_declared_input_types_fail_closed_before_backend(self):
        register_language_family(
            self.host,
            {
                "prolog": [self._brain("prolog-input-types")],
                "python": [self._brain("python-input-types")],
                "nim": [self._brain("nim-input-types")],
            },
        )
        cases = (
            (
                "zara:expert/prolog",
                "inspect",
                {"source": [], "source_generation": "generation-prolog"},
            ),
            (
                "zara:expert/python",
                "match",
                {"path": "module.py", "source_generation": {}},
            ),
            (
                "zara:expert/nim",
                "repair.preview",
                {
                    "source": "proc main() = discard",
                    "source_generation": "generation-nim",
                    "diagnostic_ref": [],
                },
            ),
            (
                "zara:expert/nim",
                "repair.apply",
                {
                    "repair": [],
                    "expected_preimage": "sha256:fixture",
                    "source_generation": "generation-nim",
                },
            ),
        )
        for expert_id, operation, payload in cases:
            with self.subTest(expert_id=expert_id, operation=operation):
                handler = make_language_expert_handler(self.host, expert_id)
                with self.assertRaisesRegex(ExpertError, "invalid input field type"):
                    handler(expert_operation=operation, **payload)
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
