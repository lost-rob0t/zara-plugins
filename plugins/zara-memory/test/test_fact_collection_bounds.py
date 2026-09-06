import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_memory.domain import MemoryError, MemorySchema, MemoryService


class NeverCalledBackend:
    def remember(self, **kwargs):
        raise AssertionError("backend remember called")


class FactCollectionBoundsTests(unittest.TestCase):
    def setUp(self):
        self.memory = MemoryService(NeverCalledBackend())
        self.memory.register_schema(
            MemorySchema(
                name="coding.workflow",
                allowed_scopes=frozenset({"project"}),
                allowed_fact_predicates=frozenset({"workflow_state"}),
            )
        )

    def remember(self, facts):
        return self.memory.remember(
            scope="project",
            owner="repo-a",
            text="state",
            facts=facts,
            provenance={"source": "operator"},
            memory_type="coding.workflow",
        )

    def test_rejects_non_sequence_fact_collections_before_backend(self):
        for facts in (None, 7, "workflow_state(verify)", (fact for fact in ["workflow_state(verify)"])):
            with self.subTest(facts=facts):
                with self.assertRaisesRegex(MemoryError, "facts"):
                    self.remember(facts)

    def test_rejects_more_than_64_facts_before_backend(self):
        facts = ["workflow_state(verify)"] * 65
        with self.assertRaisesRegex(MemoryError, "64"):
            self.remember(facts)


if __name__ == "__main__":
    unittest.main()
