import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.repository_evidence import build_repository_evidence


class RepositoryWorktreeEvidenceShapeTests(unittest.TestCase):
    def test_rejects_text_as_worktree_collection(self):
        snapshot = {
            "root": "/repo",
            "head": "a" * 40,
            "branch": "main",
            "dirty": False,
            "changed_paths": [],
        }

        with self.assertRaisesRegex(ValueError, "worktree evidence must be a bounded sequence"):
            build_repository_evidence(snapshot, worktrees="not-structured-worktrees")

    def test_rejects_non_mapping_worktree_entry(self):
        snapshot = {
            "root": "/repo",
            "head": "a" * 40,
            "branch": "main",
            "dirty": False,
            "changed_paths": [],
        }

        with self.assertRaisesRegex(ValueError, "worktree evidence entry must be structured"):
            build_repository_evidence(snapshot, worktrees=["not-a-record"])


if __name__ == "__main__":
    unittest.main()
