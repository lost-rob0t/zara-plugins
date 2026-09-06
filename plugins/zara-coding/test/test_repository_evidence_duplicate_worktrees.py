import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.repository_evidence import build_repository_evidence


class RepositoryEvidenceDuplicateWorktreeTests(unittest.TestCase):
    def test_rejects_duplicate_worktree_paths_before_symbolic_projection(self):
        snapshot = {
            "root": "/srv/demo",
            "head": "a" * 40,
            "branch": "main",
            "dirty": False,
            "changed_paths": [],
        }
        worktree = {"path": "/srv/demo-work", "head": "b" * 40, "locked": None}

        with self.assertRaisesRegex(ValueError, "duplicate.*worktree"):
            build_repository_evidence(snapshot, worktrees=[worktree, dict(worktree)])


if __name__ == "__main__":
    unittest.main()
