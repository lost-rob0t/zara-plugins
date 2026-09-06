import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError, RepositoryInspector


class WorktreeObjectIdTests(unittest.TestCase):
    def test_worktree_record_rejects_malformed_head_object_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worktree = root / "repo"
            worktree.mkdir()
            inspector = RepositoryInspector((root,))
            for object_id in ("a" * 39, "a" * 41, "g" * 40, "not-an-object-id"):
                with self.subTest(object_id=object_id):
                    with self.assertRaisesRegex(CodingError, "malformed worktree HEAD object ID"):
                        inspector._normalize_worktree_record(
                            {
                                "worktree": str(worktree),
                                "HEAD": object_id,
                                "branch": "refs/heads/main",
                            }
                        )

    def test_worktree_record_keeps_missing_head_as_malformed_structure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worktree = root / "repo"
            worktree.mkdir()
            inspector = RepositoryInspector((root,))
            with self.assertRaisesRegex(CodingError, "malformed structured output"):
                inspector._normalize_worktree_record(
                    {
                        "worktree": str(worktree),
                        "HEAD": "",
                        "branch": "refs/heads/main",
                    }
                )

    def test_worktree_record_accepts_sha1_and_sha256_head_object_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worktree = root / "repo"
            worktree.mkdir()
            inspector = RepositoryInspector((root,))
            for object_id in ("a" * 40, "b" * 64):
                with self.subTest(length=len(object_id)):
                    self.assertEqual(
                        inspector._normalize_worktree_record(
                            {
                                "worktree": str(worktree),
                                "HEAD": object_id,
                                "branch": "refs/heads/main",
                            }
                        )["head"],
                        object_id,
                    )


if __name__ == "__main__":
    unittest.main()
