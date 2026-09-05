import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError
from zara_coding.spec_verify import _repository_payload


class RepositoryVerificationHeadShapeTests(unittest.TestCase):
    def test_payload_rejects_non_object_id_snapshot_head(self):
        evidence = {
            "source_class": "repository",
            "trust_class": "observed",
            "freshness": "current",
            "snapshot": {"root": "/repo", "head": "not-a-git-object-id"},
            "state_ref": {"root": "/repo", "head": "not-a-git-object-id"},
            "values": {
                "repository_head": {"root": "/repo", "head": "not-a-git-object-id"},
                "repository_branch": {"root": "/repo", "branch": "main"},
                "repository_clean": {"root": "/repo", "dirty": False},
                "repository_changed_path": [],
                "worktree_locked": [],
            },
        }

        with self.assertRaisesRegex(CodingError, "head must be a full Git object ID"):
            _repository_payload(evidence)


if __name__ == "__main__":
    unittest.main()
