import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_memory.domain import MemoryError, MemorySchema, MemoryService


class OversizedFactBackend:
    def recall(self, **kwargs):
        return [
            {
                "id": "memory-1",
                "scope": "project",
                "owner": "repo-a",
                "text": "state",
                "type": "coding.workflow",
                "created_at": "2026-09-06T00:00:00Z",
                "provenance": {"source": "operator"},
                "facts": ["workflow_state(verify)"] * 65,
            }
        ]


class BackendFactBoundsTests(unittest.TestCase):
    def test_rejects_more_than_64_facts_in_backend_memory(self):
        memory = MemoryService(OversizedFactBackend())
        memory.register_schema(
            MemorySchema(
                name="coding.workflow",
                allowed_scopes=frozenset({"project"}),
                allowed_fact_predicates=frozenset({"workflow_state"}),
            )
        )

        with self.assertRaisesRegex(MemoryError, "64"):
            memory.recall(scope="project", owner="repo-a", memory_type="coding.workflow")


if __name__ == "__main__":
    unittest.main()
