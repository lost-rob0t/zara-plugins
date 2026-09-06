import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_memory.domain import MemoryError, MemorySchema, MemoryService


class Backend:
    def __init__(self, provenance):
        self.provenance = provenance

    def recall(self, **kwargs):
        return [
            {
                "id": "memory-1",
                "scope": kwargs["scope"],
                "owner": kwargs["owner"],
                "text": "verified fact",
                "type": "coding.workflow",
                "created_at": "2026-09-06T00:00:00Z",
                "provenance": self.provenance,
                "facts": ["workflow_state(verified)"],
            }
        ]


class BackendProvenanceTests(unittest.TestCase):
    def memory(self, provenance):
        service = MemoryService(Backend(provenance))
        service.register_schema(
            MemorySchema(
                name="coding.workflow",
                allowed_scopes=frozenset({"project"}),
                allowed_fact_predicates=frozenset({"workflow_state"}),
            )
        )
        return service

    def test_recall_rejects_empty_backend_provenance(self):
        with self.assertRaisesRegex(MemoryError, "missing provenance"):
            self.memory({}).recall(scope="project", owner="repo-a")

    def test_recall_accepts_non_empty_backend_provenance(self):
        result = self.memory({"source": "test"}).recall(scope="project", owner="repo-a")
        self.assertEqual(result[0]["provenance"], {"source": "test"})


if __name__ == "__main__":
    unittest.main()
