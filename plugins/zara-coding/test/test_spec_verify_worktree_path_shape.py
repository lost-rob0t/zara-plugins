import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError
from zara_coding.spec_verify import _repository_payload


class RepositoryVerificationWorktreePathShapeTests(unittest.TestCase):
    def _evidence(self, path):
        head = "a" * 40
        return {
            "source_class": "repository",
            "trust_class": "observed",
            "freshness": "current",
            "snapshot": {"root": "/repo", "head": head},
            "state_ref": {"root": "/repo", "head": head},
            "values": {
                "repository_head": {"root": "/repo", "head": head},
                "repository_branch": {"root": "/repo", "branch": "main"},
                "repository_clean": {"root": "/repo", "dirty": False},
                "repository_changed_path": [],
                "worktree_locked": [
                    {"path": path, "head": head, "locked": True},
                ],
            },
        }

    def test_payload_rejects_relative_worktree_path(self):
        with self.assertRaisesRegex(CodingError, "worktree path must be absolute"):
            _repository_payload(self._evidence("relative/worktree"))

    def test_payload_rejects_worktree_path_with_nul(self):
        with self.assertRaisesRegex(CodingError, "worktree path must not contain NUL"):
            _repository_payload(self._evidence("/repo/worktree\x00escape"))


if __name__ == "__main__":
    unittest.main()
