import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError
from zara_coding.spec_verify import _repository_payload


class RepositoryVerificationRootShapeTests(unittest.TestCase):
    def _evidence(self, root):
        head = "a" * 40
        return {
            "source_class": "repository",
            "trust_class": "observed",
            "freshness": "current",
            "snapshot": {"root": root, "head": head},
            "state_ref": {"root": root, "head": head},
            "values": {
                "repository_head": {"root": root, "head": head},
                "repository_branch": {"root": root, "branch": "main"},
                "repository_clean": {"root": root, "dirty": False},
                "repository_changed_path": [],
                "worktree_locked": [],
            },
        }

    def test_payload_rejects_relative_repository_root(self):
        with self.assertRaisesRegex(CodingError, "repository root must be absolute"):
            _repository_payload(self._evidence("relative/repo"))

    def test_payload_rejects_repository_root_with_nul(self):
        with self.assertRaisesRegex(CodingError, "repository root must not contain NUL"):
            _repository_payload(self._evidence("/repo\x00escape"))


if __name__ == "__main__":
    unittest.main()
