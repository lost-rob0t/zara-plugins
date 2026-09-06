import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_memory.domain import MemoryError, MemorySchema, MemoryService


class Backend:
    def remember(self, **kwargs):
        return {
            "id": "memory-1",
            "scope": kwargs["scope"],
            "owner": kwargs["owner"],
            "text": kwargs["text"],
            "facts": list(kwargs["facts"]),
            "provenance": dict(kwargs["provenance"]),
            "type": kwargs["memory_type"],
            "created_at": "2026-09-06T00:00:00Z",
        }


class FactTermShapeTests(unittest.TestCase):
    def setUp(self):
        self.memory = MemoryService(Backend())
        self.memory.register_schema(
            MemorySchema(
                name="coding.workflow",
                allowed_scopes=frozenset({"project"}),
                allowed_fact_predicates=frozenset({"workflow_state"}),
            )
        )

    def remember(self, fact):
        return self.memory.remember(
            scope="project",
            owner="repo-a",
            text="state",
            facts=[fact],
            provenance={"source": "test"},
            memory_type="coding.workflow",
        )

    def test_rejects_incomplete_or_trailing_junk_fact_terms(self):
        for fact in ("workflow_state(", "workflow_state(verify))junk"):
            with self.subTest(fact=fact):
                with self.assertRaisesRegex(MemoryError, "predicate term"):
                    self.remember(fact)

    def test_accepts_complete_fact_term_with_optional_period(self):
        self.assertEqual(self.remember("workflow_state(verify)")["facts"], ["workflow_state(verify)"])
        self.assertEqual(self.remember("workflow_state(verify).")["facts"], ["workflow_state(verify)"])


if __name__ == "__main__":
    unittest.main()
