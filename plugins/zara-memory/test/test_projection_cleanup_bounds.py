import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_memory.domain import MemoryError, MemoryService


class ProjectionBackend:
    def __init__(self, projection_ids):
        self.projection_ids = projection_ids

    def forget(self, **kwargs):
        return {"removed": True, "projection_ids": self.projection_ids}


class ProjectionCleanupBoundsTests(unittest.TestCase):
    def forget(self, projection_ids):
        return MemoryService(ProjectionBackend(projection_ids)).forget(
            "memory-1", scope="project", owner="repo-a"
        )

    def test_rejects_more_than_64_projection_ids(self):
        with self.assertRaisesRegex(MemoryError, "64"):
            self.forget([f"projection-{index}" for index in range(65)])

    def test_rejects_empty_projection_ids(self):
        with self.assertRaisesRegex(MemoryError, "projection"):
            self.forget([""])

    def test_rejects_oversized_projection_ids(self):
        with self.assertRaisesRegex(MemoryError, "128"):
            self.forget(["p" * 129])


if __name__ == "__main__":
    unittest.main()
