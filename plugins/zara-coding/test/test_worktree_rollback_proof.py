import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError, RepositoryInspector
from zara_coding.worktree import add_detached_locked_worktree


class WorktreeRollbackProofTests(unittest.TestCase):
    def test_failed_lock_does_not_claim_rollback_while_target_remains_registered(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            target = root / "task-17"
            calls = []

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                args = tuple(argv[3:])
                if args == ("rev-parse", "--show-toplevel"):
                    output = f"{repo.resolve()}\n"
                elif args == ("rev-parse", "--verify", f"{'a' * 40}^{{commit}}"):
                    output = f"{'a' * 40}\n"
                elif args == ("worktree", "list", "--porcelain", "-z"):
                    output = (
                        f"worktree {repo.resolve()}\0HEAD {'b' * 40}\0branch refs/heads/main\0\0"
                        f"worktree {target.resolve()}\0HEAD {'a' * 40}\0detached\0\0"
                    )
                elif args == ("worktree", "lock", "--reason", "coding-task:17", str(target.resolve())):
                    raise subprocess.CalledProcessError(1, argv)
                else:
                    output = ""
                return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "rollback could not safely remove"):
                add_detached_locked_worktree(inspector, repo, target, "a" * 40, "coding-task:17")

            argv_calls = [call[0][3:] for call in calls]
            self.assertIn(["worktree", "remove", str(target.resolve())], argv_calls)
            self.assertGreaterEqual(argv_calls.count(["worktree", "list", "--porcelain", "-z"]), 3)


if __name__ == "__main__":
    unittest.main()
