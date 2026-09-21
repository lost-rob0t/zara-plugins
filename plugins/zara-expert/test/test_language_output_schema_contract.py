import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertHost
from zara_expert.language_family import descriptors, register_language_family
from zara_expert.language_handler import make_language_expert_handler


EXPERT_IDS = (
    "zara:expert/prolog",
    "zara:expert/python",
    "zara:expert/nim",
)


class StructuredBackend:
    def run(self, request):
        predicate = request["capability"].predicate
        if predicate == "language_applicable":
            results = ["applicable(true)."]
            trace = ["rule:match"]
        elif predicate == "language_evidence":
            results = ["evidence(symbolic_language_fact)."]
            trace = ["rule:inspect"]
        elif predicate == "language_diagnostic":
            results = ["diagnostic(symbolic_issue,deterministic)."]
            trace = ["rule:diagnose"]
        elif predicate == "language_repair_preview":
            results = ["repair_preview(rewrite(symbolic_issue,safe_candidate))."]
            trace = ["rule:repair-preview"]
        elif predicate == "language_repair_verify":
            results = ["verified(false)."]
            trace = ["rule:repair-verify"]
        elif predicate == "language_style_rules":
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
            if item["expert_id"] in set(EXPERT_IDS)
        }

    def tearDown(self):
        self.temporary.cleanup()

    def _declared_output(self, expert_id, operation):
        descriptor = self.descriptors[expert_id]
        operation_descriptor = next(
            item for item in descriptor["operations"] if item["operation_id"] == operation
        )
        fields = operation_descriptor["output_schema"]["fields"]
        return {field["name"]: field for field in fields}

    def _assert_common_symbolic_envelope(self, outcome):
        self.assertEqual(outcome["usage"], {"model_calls": 0})
        self.assertEqual(outcome["effect_receipts"], [])
        self.assertTrue(outcome["evidence_refs"])
        self.assertTrue(
            all(ref.startswith("evidence:language:sha256:") for ref in outcome["evidence_refs"])
        )

    def _assert_declared_success_data(self, expert_id, operation, payload):
        handler = make_language_expert_handler(self.host, expert_id)
        outcome = handler(expert_operation=operation, **payload)
        self.assertEqual(outcome["verdict"], "succeeded")
        self._assert_common_symbolic_envelope(outcome)

        declared = self._declared_output(expert_id, operation)
        data = outcome["data"]
        self.assertFalse(
            set(data) - set(declared),
            f"{expert_id} {operation} leaked undeclared output fields: "
            f"{sorted(set(data) - set(declared))}",
        )
        for name, field in declared.items():
            if field["required"]:
                self.assertIn(name, data, f"{expert_id} {operation} omitted required {name}")
        return data

    def _assert_declared_blocked_data(self, expert_id, operation, payload):
        handler = make_language_expert_handler(self.host, expert_id)
        outcome = handler(expert_operation=operation, **payload)
        self.assertEqual(outcome["verdict"], "blocked")
        self._assert_common_symbolic_envelope(outcome)

        declared = self._declared_output(expert_id, operation)
        data = outcome["data"]
        self.assertFalse(
            set(data) - set(declared),
            f"{expert_id} {operation} leaked undeclared blocked-output fields: "
            f"{sorted(set(data) - set(declared))}",
        )
        return data

    def test_match_success_matches_public_output_schema(self):
        for index, expert_id in enumerate(EXPERT_IDS, start=1):
            with self.subTest(expert_id=expert_id):
                data = self._assert_declared_success_data(
                    expert_id,
                    "match",
                    {
                        "path": f"src/router-{index}.fixture",
                        "source_generation": f"generation:match:{index}",
                    },
                )
                self.assertIs(data["applicable"], True)

    def test_inspect_success_matches_public_output_schema(self):
        for index, expert_id in enumerate(EXPERT_IDS, start=1):
            with self.subTest(expert_id=expert_id):
                data = self._assert_declared_success_data(
                    expert_id,
                    "inspect",
                    {
                        "source": f"symbolic source {index}",
                        "source_generation": f"generation:inspect:{index}",
                    },
                )
                self.assertIsInstance(data["result"], dict)

    def test_diagnose_success_matches_public_output_schema(self):
        for index, expert_id in enumerate(EXPERT_IDS, start=1):
            with self.subTest(expert_id=expert_id):
                data = self._assert_declared_success_data(
                    expert_id,
                    "diagnose",
                    {
                        "source": f"symbolic source {index}",
                        "source_generation": f"generation:diagnose:{index}",
                    },
                )
                self.assertEqual(
                    data["diagnostics"],
                    ["diagnostic(symbolic_issue,deterministic)."],
                )

    def test_repair_preview_success_matches_public_output_schema(self):
        for index, expert_id in enumerate(EXPERT_IDS, start=1):
            with self.subTest(expert_id=expert_id):
                data = self._assert_declared_success_data(
                    expert_id,
                    "repair.preview",
                    {
                        "source": f"symbolic source {index}",
                        "source_generation": f"generation:repair-preview:{index}",
                        "diagnostic_ref": f"diagnostic:{index}",
                    },
                )
                self.assertEqual(
                    data["repair"],
                    {
                        "symbolic_terms": [
                            "repair_preview(rewrite(symbolic_issue,safe_candidate))."
                        ]
                    },
                )

    def test_repair_verify_blocked_output_is_closed_and_zero_model(self):
        for index, expert_id in enumerate(EXPERT_IDS, start=1):
            with self.subTest(expert_id=expert_id):
                data = self._assert_declared_blocked_data(
                    expert_id,
                    "repair.verify",
                    {
                        "original_source": f"before {index}",
                        "candidate_source": f"after {index}",
                        "source_generation": f"generation:repair-verify:{index}",
                    },
                )
                self.assertEqual(data, {})

    def test_style_rules_success_matches_public_output_schema(self):
        fixtures = {
            "zara:expert/prolog": "route(Request) --> command(Request).",
            "zara:expert/python": "def route(request):\n    return request\n",
            "zara:expert/nim": "proc route(request: string): string = request\n",
        }
        for expert_id, source in fixtures.items():
            with self.subTest(expert_id=expert_id):
                data = self._assert_declared_success_data(
                    expert_id,
                    "style.rules",
                    {"source": source, "project_style": "style:project-default"},
                )
                self.assertEqual(
                    data["style_provenance"],
                    [self.descriptors[expert_id]["source_reference"]],
                )

    def test_explanation_success_matches_public_output_schema(self):
        for index, expert_id in enumerate(EXPERT_IDS, start=1):
            with self.subTest(expert_id=expert_id):
                data = self._assert_declared_success_data(
                    expert_id,
                    "explain",
                    {
                        "decision_ref": f"decision:output-schema-{index}",
                        "source_generation": f"generation:output-schema-{index}",
                    },
                )
                self.assertEqual(
                    data["explanation"]["trace"],
                    ["rule:explain"],
                )


if __name__ == "__main__":
    unittest.main()
