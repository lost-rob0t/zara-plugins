import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError
from zara_coding.spec_verify import _repository_payload


class RepositoryVerificationDuplicateEvidenceTests(unittest.TestCase):
    @staticmethod
    def evidence(*, changed_paths=None, worktrees=None) -> dict[str, object]:
        changed_paths = [] if changed_paths is None else changed_paths
        worktrees = [] if worktrees is None else worktrees
        head = "a" * 40
        root = "/srv/demo"
        return {
            "source_class": "repository",
            "trust_class": "observed",
            "freshness": "current",
            "snapshot": {"root": root, "head": head},
            "state_ref": {"root": root, "head": head},
            "values": {
                "repository_head": {"root": root, "head": head},
                "repository_branch": {"root": root, "branch": "main"},
                "repository_clean": {"root": root, "dirty": bool(changed_paths)},
                "repository_changed_path": [
                    {"root": root, "path": path} for path in changed_paths
                ],
                "worktree_locked": worktrees,
            },
        }

    def test_rejects_duplicate_changed_path_assertion_values(self) -> None:
        with self.assertRaisesRegex(CodingError, "duplicate changed paths"):
            _repository_payload(self.evidence(changed_paths=["src/app.py", "src/app.py"]))

    def test_rejects_duplicate_worktree_assertion_values(self) -> None:
        worktree = {"path": "/srv/demo-wt", "head": "b" * 40, "locked": True}
        with self.assertRaisesRegex(CodingError, "duplicate worktree paths"):
            _repository_payload(self.evidence(worktrees=[worktree, dict(worktree)]))


if __name__ == "__main__":
    unittest.main()
