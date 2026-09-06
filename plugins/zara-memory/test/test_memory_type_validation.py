import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_memory.domain import MemoryError, MemorySchema, MemoryService


class NeverCalledBackend:
    def remember(self, **kwargs):
        raise AssertionError("backend remember called")

    def recall(self, **kwargs):
        raise AssertionError("backend recall called")


class MemoryTypeValidationTests(unittest.TestCase):
    def setUp(self):
        self.memory = MemoryService(NeverCalledBackend())
        self.memory.register_schema(
            MemorySchema(
                name="coding.workflow",
                allowed_scopes=frozenset({"project"}),
                allowed_fact_predicates=frozenset({"workflow_state"}),
            )
        )

    def test_remember_rejects_malformed_memory_type_before_backend(self):
        for memory_type in ([], {}, "", "   ", 7):
            with self.subTest(memory_type=memory_type):
                with self.assertRaisesRegex(MemoryError, "memory type"):
                    self.memory.remember(
                        scope="project",
                        owner="repo-a",
                        text="state",
                        facts=["workflow_state(verify)"],
                        provenance={"source": "operator"},
                        memory_type=memory_type,
                    )

    def test_recall_rejects_malformed_memory_type_before_backend(self):
        for memory_type in ([], {}, "", "   ", 7):
            with self.subTest(memory_type=memory_type):
                with self.assertRaisesRegex(MemoryError, "memory type"):
                    self.memory.recall(
                        scope="project",
                        owner="repo-a",
                        memory_type=memory_type,
                    )


if __name__ == "__main__":
    unittest.main()
