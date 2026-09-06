import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError, RepositoryInspector


class CommitTreeObjectIdTests(unittest.TestCase):
    def test_commit_rejects_malformed_staged_tree_object_id_before_commit_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            parent = "a" * 40

            def run(argv, **kwargs):
                args = tuple(argv[3:])
                outputs = {
                    ("rev-parse", "--show-toplevel"): f"{repo.resolve()}\n",
                    ("symbolic-ref", "-q", "HEAD"): "refs/heads/main\n",
                    ("rev-parse", "HEAD"): parent + "\n",
                    ("write-tree",): "not-a-tree-id\n",
                    ("rev-parse", f"{parent}^{{tree}}"): "b" * 40 + "\n",
                }
                if args and args[0] == "commit-tree":
                    self.fail("malformed staged tree reached commit-tree")
                return subprocess.CompletedProcess(argv, 0, stdout=outputs.get(args, ""), stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "malformed staged tree object ID"):
                inspector.commit(repo, "message", parent)

    def test_commit_rejects_malformed_parent_tree_object_id_before_commit_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            parent = "a" * 40
            tree = "b" * 40

            def run(argv, **kwargs):
                args = tuple(argv[3:])
                outputs = {
                    ("rev-parse", "--show-toplevel"): f"{repo.resolve()}\n",
                    ("symbolic-ref", "-q", "HEAD"): "refs/heads/main\n",
                    ("rev-parse", "HEAD"): parent + "\n",
                    ("write-tree",): tree + "\n",
                    ("rev-parse", f"{parent}^{{tree}}"): "not-a-tree-id\n",
                }
                if args and args[0] == "commit-tree":
                    self.fail("malformed parent tree reached commit-tree")
                return subprocess.CompletedProcess(argv, 0, stdout=outputs.get(args, ""), stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "malformed parent tree object ID"):
                inspector.commit(repo, "message", parent)


if __name__ == "__main__":
    unittest.main()
