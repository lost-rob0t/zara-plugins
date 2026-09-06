import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.repository_evidence import build_repository_evidence


class RepositoryEvidencePathTests(unittest.TestCase):
    def snapshot(self, root):
        return {
            "root": root,
            "head": "a" * 40,
            "branch": "main",
            "dirty": False,
            "changed_paths": (),
        }

    def test_rejects_parent_segment_in_repository_root(self):
        with self.assertRaisesRegex(ValueError, "repository snapshot root must be canonical"):
            build_repository_evidence(self.snapshot("/srv/repos/../other"))

    def test_rejects_current_segment_in_repository_root(self):
        with self.assertRaisesRegex(ValueError, "repository snapshot root must be canonical"):
            build_repository_evidence(self.snapshot("/srv/./repo"))

    def test_rejects_noncanonical_worktree_path(self):
        with self.assertRaisesRegex(ValueError, "worktree evidence path must be canonical"):
            build_repository_evidence(
                self.snapshot("/srv/repo"),
                worktrees=(
                    {"path": "/srv/worktrees/../shared", "head": "b" * 40, "locked": "task"},
                ),
            )

    def test_accepts_canonical_absolute_paths(self):
        evidence = build_repository_evidence(
            self.snapshot("/srv/repo"),
            worktrees=(
                {"path": "/srv/worktrees/task-1", "head": "b" * 64, "locked": "task"},
            ),
        )
        self.assertEqual(evidence["snapshot"]["root"], "/srv/repo")
        self.assertEqual(
            evidence["values"]["worktree_locked"][0]["path"],
            "/srv/worktrees/task-1",
        )


if __name__ == "__main__":
    unittest.main()
