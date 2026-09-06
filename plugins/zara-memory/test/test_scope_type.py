import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_memory.domain import MemoryError, MemoryService


class Backend:
    def __init__(self):
        self.calls = 0

    def recall(self, **kwargs):
        self.calls += 1
        return []


class ScopeTypeTests(unittest.TestCase):
    def test_recall_rejects_non_text_scope_before_backend_dispatch(self):
        for scope in ([], {}, 0, False, object()):
            with self.subTest(scope=scope):
                backend = Backend()
                memory = MemoryService(backend)
                with self.assertRaisesRegex(MemoryError, "unsupported memory scope"):
                    memory.recall(scope=scope, owner="repo-a")
                self.assertEqual(backend.calls, 0)


if __name__ == "__main__":
    unittest.main()
