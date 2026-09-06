import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError, RepositoryInspector
from zara_coding.worktree import add_detached_worktree


class WorktreeAddProofTests(unittest.TestCase):
    def test_add_rejects_zero_exit_without_registered_worktree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            target = root / "worktrees" / "task-1"
            target.parent.mkdir()

            def run(argv, **kwargs):
                args = tuple(argv[3:])
                if args == ("rev-parse", "--show-toplevel"):
                    output = f"{repo.resolve()}\n"
                elif args == ("rev-parse", "--verify", f"{'a' * 40}^{{commit}}"):
                    output = f"{'a' * 40}\n"
                elif args == ("worktree", "list", "--porcelain", "-z"):
                    output = f"worktree {repo.resolve()}\x00HEAD {'a' * 40}\x00branch refs/heads/main\x00\x00"
                else:
                    output = ""
                return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "created worktree was not registered"):
                add_detached_worktree(inspector, repo, target, "a" * 40)

    def test_add_rejects_registered_worktree_with_changed_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            target = root / "worktrees" / "task-1"
            target.parent.mkdir()

            def run(argv, **kwargs):
                args = tuple(argv[3:])
                if args == ("rev-parse", "--show-toplevel"):
                    output = f"{repo.resolve()}\n"
                elif args == ("rev-parse", "--verify", f"{'a' * 40}^{{commit}}"):
                    output = f"{'a' * 40}\n"
                elif args == ("worktree", "list", "--porcelain", "-z"):
                    output = (
                        f"worktree {repo.resolve()}\x00HEAD {'a' * 40}\x00branch refs/heads/main\x00\x00"
                        f"worktree {target.resolve()}\x00HEAD {'b' * 40}\x00detached\x00\x00"
                    )
                else:
                    output = ""
                return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "created worktree identity changed"):
                add_detached_worktree(inspector, repo, target, "a" * 40)


if __name__ == "__main__":
    unittest.main()
