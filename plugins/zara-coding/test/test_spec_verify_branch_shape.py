import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError
from zara_coding.spec_verify import _repository_payload


class RepositoryVerificationBranchShapeTests(unittest.TestCase):
    def _evidence(self, branch):
        head = "a" * 40
        root = "/repo"
        return {
            "source_class": "repository",
            "trust_class": "observed",
            "freshness": "current",
            "snapshot": {"root": root, "head": head},
            "state_ref": {"root": root, "head": head},
            "values": {
                "repository_head": {"root": root, "head": head},
                "repository_branch": {"root": root, "branch": branch},
                "repository_clean": {"root": root, "dirty": False},
                "repository_changed_path": [],
                "worktree_locked": [],
            },
        }

    def test_payload_rejects_branch_with_nul(self):
        with self.assertRaisesRegex(CodingError, "branch must be single-line text"):
            _repository_payload(self._evidence("main\x00other"))

    def test_payload_rejects_multiline_branch(self):
        with self.assertRaisesRegex(CodingError, "branch must be single-line text"):
            _repository_payload(self._evidence("main\nother"))

    def test_payload_accepts_detached_identity(self):
        payload = _repository_payload(self._evidence("DETACHED"))
        self.assertEqual(payload["branch"], "DETACHED")


if __name__ == "__main__":
    unittest.main()
