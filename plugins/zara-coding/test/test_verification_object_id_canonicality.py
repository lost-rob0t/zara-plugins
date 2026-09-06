import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError
from zara_coding.repository_evidence import build_repository_evidence
from zara_coding.spec_verify import _repository_payload


class VerificationObjectIdCanonicalityTests(unittest.TestCase):
    @staticmethod
    def evidence(head: str, *, worktree_head: str | None = None) -> dict[str, object]:
        worktrees = []
        if worktree_head is not None:
            worktrees.append({"path": "/srv/demo-worktree", "head": worktree_head, "locked": True})
        return {
            "source_class": "repository",
            "trust_class": "observed",
            "freshness": "current",
            "snapshot": {"root": "/srv/demo", "head": head},
            "state_ref": {"root": "/srv/demo", "head": head},
            "values": {
                "repository_head": {"root": "/srv/demo", "head": head},
                "repository_branch": {"root": "/srv/demo", "branch": "main"},
                "repository_clean": {"root": "/srv/demo", "dirty": False},
                "repository_changed_path": [],
                "worktree_locked": worktrees,
            },
        }

    def test_builder_rejects_uppercase_repository_head(self) -> None:
        with self.assertRaisesRegex(ValueError, "canonical lowercase"):
            build_repository_evidence(
                {"root": "/srv/demo", "head": "A" * 40, "branch": "main", "dirty": False}
            )

    def test_builder_rejects_uppercase_worktree_head(self) -> None:
        with self.assertRaisesRegex(ValueError, "canonical lowercase"):
            build_repository_evidence(
                {"root": "/srv/demo", "head": "a" * 40, "branch": "main", "dirty": False},
                worktrees=[{"path": "/srv/demo-worktree", "head": "B" * 64, "locked": "task"}],
            )

    def test_verifier_rejects_uppercase_repository_head(self) -> None:
        with self.assertRaisesRegex(CodingError, "canonical lowercase"):
            _repository_payload(self.evidence("C" * 40))

    def test_verifier_rejects_uppercase_worktree_head(self) -> None:
        with self.assertRaisesRegex(CodingError, "canonical lowercase"):
            _repository_payload(self.evidence("c" * 40, worktree_head="D" * 64))

    def test_lowercase_sha1_and_sha256_remain_canonical(self) -> None:
        for head in ("a" * 40, "b" * 64):
            with self.subTest(length=len(head)):
                built = build_repository_evidence(
                    {"root": "/srv/demo", "head": head, "branch": "main", "dirty": False},
                    worktrees=[{"path": "/srv/demo-worktree", "head": head, "locked": None}],
                )
                self.assertEqual(_repository_payload(built)["head"], head)


if __name__ == "__main__":
    unittest.main()
