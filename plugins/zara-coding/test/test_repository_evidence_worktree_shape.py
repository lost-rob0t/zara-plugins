import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.repository_evidence import build_repository_evidence


class RepositoryWorktreeEvidenceShapeTests(unittest.TestCase):
    def _snapshot(self):
        return {
            "root": "/repo",
            "head": "a" * 40,
            "branch": "main",
            "dirty": False,
            "changed_paths": [],
        }

    def _worktree(self, path):
        return {"path": path, "head": "b" * 40, "locked": None}

    def test_rejects_text_as_worktree_collection(self):
        with self.assertRaisesRegex(ValueError, "worktree evidence must be a bounded sequence"):
            build_repository_evidence(self._snapshot(), worktrees="not-structured-worktrees")

    def test_rejects_non_mapping_worktree_entry(self):
        with self.assertRaisesRegex(ValueError, "worktree evidence entry must be structured"):
            build_repository_evidence(self._snapshot(), worktrees=["not-a-record"])

    def test_rejects_relative_worktree_path(self):
        with self.assertRaisesRegex(ValueError, "worktree evidence path must be absolute"):
            build_repository_evidence(self._snapshot(), worktrees=[self._worktree("relative/worktree")])

    def test_rejects_worktree_path_with_nul(self):
        with self.assertRaisesRegex(ValueError, "worktree evidence path must not contain NUL"):
            build_repository_evidence(self._snapshot(), worktrees=[self._worktree("/repo/worktree\x00escape")])


if __name__ == "__main__":
    unittest.main()
