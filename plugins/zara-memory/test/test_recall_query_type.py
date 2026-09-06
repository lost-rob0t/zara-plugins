import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_memory.domain import MemoryError, MemoryService, MemorySchema


class RecordingBackend:
    def __init__(self):
        self.calls = 0

    def recall(self, **kwargs):
        self.calls += 1
        return []


class RecallQueryTypeTests(unittest.TestCase):
    def setUp(self):
        self.backend = RecordingBackend()
        self.memory = MemoryService(self.backend)
        self.memory.register_schema(
            MemorySchema(
                name="coding.workflow",
                allowed_scopes=frozenset({"project"}),
                allowed_fact_predicates=frozenset({"workflow_state"}),
            )
        )

    def test_recall_rejects_non_text_query_before_backend_dispatch(self):
        for query in (0, False, 1.5, [], {}, object()):
            with self.subTest(query=query):
                with self.assertRaisesRegex(MemoryError, "memory query must be text"):
                    self.memory.recall(scope="project", owner="repo-a", query=query)
                self.assertEqual(self.backend.calls, 0)

    def test_recall_accepts_text_and_none_queries(self):
        self.memory.recall(scope="project", owner="repo-a", query=None)
        self.memory.recall(scope="project", owner="repo-a", query="verify")
        self.assertEqual(self.backend.calls, 2)


if __name__ == "__main__":
    unittest.main()
