import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError, RepositoryInspector
from zara_coding.worktree import remove_detached_worktree


class WorktreeRemoveTests(unittest.TestCase):
    def _inspector(self, root, repo, target, *, head=None, locked=None, remove_path=True):
        head = head or "a" * 40
        removed = False
        calls = []

        def run(argv, **kwargs):
            nonlocal removed
            calls.append((argv, kwargs))
            args = tuple(argv[3:])
            if args == ("rev-parse", "--show-toplevel"):
                output = f"{repo.resolve()}\n"
            elif args == ("worktree", "list", "--porcelain", "-z"):
                primary = f"worktree {repo.resolve()}\0HEAD {'b' * 40}\0branch refs/heads/main\0\0"
                if removed:
                    output = primary
                else:
                    lock_field = "" if locked is None else f"locked {locked}\0"
                    output = primary + f"worktree {target.resolve()}\0HEAD {head}\0detached\0{lock_field}\0"
            elif args == ("worktree", "remove", str(target.resolve())):
                removed = True
                if remove_path:
                    target.rmdir()
                output = ""
            else:
                output = ""
            return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

        return RepositoryInspector((root,), runner=run), calls

    def test_remove_requires_exact_unlocked_detached_identity_and_proves_absence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            target = root / "task-1"
            repo.mkdir()
            target.mkdir()
            inspector, calls = self._inspector(root, repo, target)

            evidence = remove_detached_worktree(inspector, repo, target, "a" * 40)

            self.assertEqual(
                evidence,
                {"path": str(target.resolve()), "head": "a" * 40, "removed": True},
            )
            self.assertFalse(target.exists())
            self.assertIn(
                ["worktree", "remove", str(target.resolve())],
                [call[0][3:] for call in calls],
            )
            self.assertTrue(all(call[1]["shell"] is False for call in calls))

    def test_remove_refuses_locked_or_stale_worktree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            target = root / "task-1"
            repo.mkdir()
            target.mkdir()

            locked, _ = self._inspector(root, repo, target, locked="coding-task:17")
            with self.assertRaisesRegex(CodingError, "locked"):
                remove_detached_worktree(locked, repo, target, "a" * 40)

            stale, _ = self._inspector(root, repo, target, head="c" * 40)
            with self.assertRaisesRegex(CodingError, "HEAD changed"):
                remove_detached_worktree(stale, repo, target, "a" * 40)

    def test_remove_does_not_report_success_when_path_remains(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            target = root / "task-1"
            repo.mkdir()
            target.mkdir()
            inspector, _ = self._inspector(root, repo, target, remove_path=False)

            with self.assertRaisesRegex(CodingError, "path remained"):
                remove_detached_worktree(inspector, repo, target, "a" * 40)


if __name__ == "__main__":
    unittest.main()
