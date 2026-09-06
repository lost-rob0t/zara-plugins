import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_memory.domain import MemoryError, MemoryService


class DuplicateProjectionBackend:
    def forget(self, **kwargs):
        return {
            "removed": True,
            "projection_ids": ["projection-1", "projection-1"],
        }


class DuplicateProjectionIdentityTests(unittest.TestCase):
    def test_rejects_duplicate_projection_ids(self):
        service = MemoryService(DuplicateProjectionBackend())

        with self.assertRaisesRegex(MemoryError, "duplicate projection id"):
            service.forget("memory-1", scope="session", owner="operator")


if __name__ == "__main__":
    unittest.main()
