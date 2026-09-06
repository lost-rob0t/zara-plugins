import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError, RepositoryInspector
from zara_coding.worktree import lock_worktree


class WorktreeLockProofTests(unittest.TestCase):
    def test_lock_rejects_zero_exit_without_requested_lock_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            target = root / "task-1"
            repo.mkdir()
            target.mkdir()

            def run(argv, **kwargs):
                args = tuple(argv[3:])
                if args == ("rev-parse", "--show-toplevel"):
                    output = f"{repo.resolve()}\n"
                elif args == ("worktree", "list", "--porcelain", "-z"):
                    output = (
                        f"worktree {repo.resolve()}\0HEAD {'b' * 40}\0branch refs/heads/main\0\0"
                        f"worktree {target.resolve()}\0HEAD {'a' * 40}\0detached\0\0"
                    )
                else:
                    output = ""
                return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "worktree lock state was not established"):
                lock_worktree(inspector, repo, target, "a" * 40, "coding-task:17")

    def test_lock_rejects_changed_identity_after_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            target = root / "task-1"
            repo.mkdir()
            target.mkdir()
            inventory_reads = 0

            def run(argv, **kwargs):
                nonlocal inventory_reads
                args = tuple(argv[3:])
                if args == ("rev-parse", "--show-toplevel"):
                    output = f"{repo.resolve()}\n"
                elif args == ("worktree", "list", "--porcelain", "-z"):
                    inventory_reads += 1
                    head = "a" * 40 if inventory_reads == 1 else "c" * 40
                    locked = "" if inventory_reads == 1 else "locked coding-task:17\0"
                    output = (
                        f"worktree {repo.resolve()}\0HEAD {'b' * 40}\0branch refs/heads/main\0\0"
                        f"worktree {target.resolve()}\0HEAD {head}\0detached\0{locked}\0"
                    )
                else:
                    output = ""
                return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "worktree identity changed after lock"):
                lock_worktree(inspector, repo, target, "a" * 40, "coding-task:17")


if __name__ == "__main__":
    unittest.main()
