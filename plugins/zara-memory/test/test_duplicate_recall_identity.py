import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_memory.domain import MemoryError, MemorySchema, MemoryService


class DuplicateBackend:
    def recall(self, **kwargs):
        item = {
            "id": "memory-1",
            "scope": kwargs["scope"],
            "owner": kwargs["owner"],
            "text": "hello",
            "type": "note",
            "created_at": "2026-09-06T00:00:00Z",
            "provenance": {"source": "test"},
            "facts": ["note(hello)"],
        }
        return [dict(item), dict(item)]


class DuplicateRecallIdentityTests(unittest.TestCase):
    def test_rejects_duplicate_memory_ids(self):
        service = MemoryService(DuplicateBackend())
        service.register_schema(
            MemorySchema(
                "note",
                frozenset({"session"}),
                frozenset({"note"}),
            )
        )

        with self.assertRaisesRegex(MemoryError, "duplicate memory id"):
            service.recall(scope="session", owner="operator", memory_type="note")


if __name__ == "__main__":
    unittest.main()
