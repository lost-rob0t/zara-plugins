import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertHost
from zara_expert.language_family import descriptors, register_language_family
from zara_expert.language_handler import make_language_expert_handler


class StructuredBackend:
    def run(self, request):
        predicate = request["capability"].predicate
        if predicate == "language_style_rules":
            results = ["style_rule(two_space_indent).", "style_provenance(project_style)."]
            trace = ["rule:style"]
        elif predicate == "language_explanation":
            results = ["explanation(decision,deterministic_symbolic_rule)."]
            trace = ["rule:explain"]
        else:
            raise AssertionError(f"unexpected predicate: {predicate}")
        return {"ok": True, "results": results, "trace": trace}


class LanguageOutputSchemaContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.host = ExpertHost(StructuredBackend(), state_root=self.root / "state")
        sources = {}
        for key in ("prolog", "python", "nim"):
            path = self.root / f"{key}.pl"
            path.write_text("% canonical-language-brain-fixture\n", encoding="utf-8")
            sources[key] = [path]
        register_language_family(self.host, sources)
        self.descriptors = {
            item["expert_id"]: item
            for item in descriptors({"prolog", "python", "nim"})
            if item["expert_id"]
            in {"zara:expert/prolog", "zara:expert/python", "zara:expert/nim"}
        }

    def tearDown(self):
        self.temporary.cleanup()

    def _assert_declared_success_data(self, expert_id, operation, payload):
        handler = make_language_expert_handler(self.host, expert_id)
        outcome = handler(expert_operation=operation, **payload)
        self.assertEqual(outcome["verdict"], "succeeded")
        self.assertEqual(outcome["usage"], {"model_calls": 0})
        self.assertEqual(outcome["effect_receipts"], [])

        descriptor = self.descriptors[expert_id]
        operation_descriptor = next(
            item for item in descriptor["operations"] if item["operation_id"] == operation
        )
        fields = operation_descriptor["output_schema"]["fields"]
        declared = {field["name"]: field for field in fields}
        data = outcome["data"]

        self.assertFalse(
            set(data) - set(declared),
            f"{expert_id} {operation} leaked undeclared output fields: "
            f"{sorted(set(data) - set(declared))}",
        )
        for name, field in declared.items():
            if field["required"]:
                self.assertIn(name, data, f"{expert_id} {operation} omitted required {name}")

    def test_style_rules_success_matches_public_output_schema(self):
        fixtures = {
            "zara:expert/prolog": "route(Request) --> command(Request).",
            "zara:expert/python": "def route(request):\n    return request\n",
            "zara:expert/nim": "proc route(request: string): string = request\n",
        }
        for expert_id, source in fixtures.items():
            with self.subTest(expert_id=expert_id):
                self._assert_declared_success_data(
                    expert_id,
                    "style.rules",
                    {"source": source, "project_style": "style:project-default"},
                )

    def test_explanation_success_matches_public_output_schema(self):
        for index, expert_id in enumerate(
            ("zara:expert/prolog", "zara:expert/python", "zara:expert/nim"), start=1
        ):
            with self.subTest(expert_id=expert_id):
                self._assert_declared_success_data(
                    expert_id,
                    "explain",
                    {
                        "decision_ref": f"decision:output-schema-{index}",
                        "source_generation": f"generation:output-schema-{index}",
                    },
                )


if __name__ == "__main__":
    unittest.main()
