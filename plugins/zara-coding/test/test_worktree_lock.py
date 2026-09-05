import json
import subprocess
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError, RepositoryInspector
from zara_coding.worktree import lock_worktree, unlock_worktree


@dataclass(frozen=True)
class PluginMetadata:
    name: str
    version: str = ""
    api_version: str = "1"
    description: str = ""


class ServicePlugin:
    pass


zara = types.ModuleType("zara")
zara_plugins = types.ModuleType("zara.plugins")
zara_plugins.PluginMetadata = PluginMetadata
zara_plugins.ServicePlugin = ServicePlugin
sys.modules.setdefault("zara", zara)
sys.modules.setdefault("zara.plugins", zara_plugins)

from zara_coding.plugin import ZaraCodingPlugin


class WorktreeLockTests(unittest.TestCase):
    def _inspector(self, root, repo, target, *, locked=None, head=None, calls=None):
        head = head or "a" * 40
        calls = calls if calls is not None else []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            args = tuple(argv[3:])
            if args == ("rev-parse", "--show-toplevel"):
                output = f"{repo.resolve()}\n"
            elif args == ("worktree", "list", "--porcelain", "-z"):
                lock_field = "" if locked is None else f"locked {locked}\0"
                output = (
                    f"worktree {repo.resolve()}\0HEAD {'b' * 40}\0branch refs/heads/main\0\0"
                    f"worktree {target.resolve()}\0HEAD {head}\0detached\0{lock_field}\0"
                )
            else:
                output = ""
            return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

        return RepositoryInspector((root,), runner=run), calls

    def test_lock_requires_exact_detached_worktree_head_and_records_bounded_reason(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            target = root / "task-1"
            repo.mkdir()
            target.mkdir()
            calls = []
            inspector, _ = self._inspector(root, repo, target, calls=calls)

            evidence = lock_worktree(inspector, repo, target, "a" * 40, "coding-task:17")

            self.assertEqual(
                evidence,
                {
                    "path": str(target.resolve()),
                    "head": "a" * 40,
                    "detached": True,
                    "locked": "coding-task:17",
                },
            )
            argv_calls = [call[0][3:] for call in calls]
            self.assertIn(
                ["worktree", "lock", "--reason", "coding-task:17", str(target.resolve())],
                argv_calls,
            )
            self.assertTrue(all(call[1]["shell"] is False for call in calls))

    def test_lock_refuses_primary_attached_stale_or_already_locked_worktrees(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            target = root / "task-1"
            repo.mkdir()
            target.mkdir()

            inspector, _ = self._inspector(root, repo, target)
            with self.assertRaisesRegex(CodingError, "primary worktree"):
                lock_worktree(inspector, repo, repo, "b" * 40, "owner")
            with self.assertRaisesRegex(CodingError, "HEAD changed"):
                lock_worktree(inspector, repo, target, "c" * 40, "owner")

            locked_inspector, _ = self._inspector(root, repo, target, locked="other-owner")
            with self.assertRaisesRegex(CodingError, "already locked"):
                lock_worktree(locked_inspector, repo, target, "a" * 40, "owner")

    def test_lock_rejects_unbounded_or_control_character_reason(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            target = root / "task-1"
            repo.mkdir()
            target.mkdir()
            inspector, _ = self._inspector(root, repo, target)

            for reason in ("", "bad\nreason", "x" * 257):
                with self.subTest(reason=reason[:10]):
                    with self.assertRaises(ValueError):
                        lock_worktree(inspector, repo, target, "a" * 40, reason)

    def test_unlock_requires_matching_coordination_reason_and_exact_head(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            target = root / "task-1"
            repo.mkdir()
            target.mkdir()
            calls = []
            inspector, _ = self._inspector(root, repo, target, locked="coding-task:17", calls=calls)

            evidence = unlock_worktree(inspector, repo, target, "a" * 40, "coding-task:17")

            self.assertEqual(
                evidence,
                {"path": str(target.resolve()), "head": "a" * 40, "detached": True, "locked": None},
            )
            self.assertIn(
                ["worktree", "unlock", str(target.resolve())],
                [call[0][3:] for call in calls],
            )

            wrong_reason, _ = self._inspector(root, repo, target, locked="other-task")
            with self.assertRaisesRegex(CodingError, "coordination reason changed"):
                unlock_worktree(wrong_reason, repo, target, "a" * 40, "coding-task:17")

    @patch("zara_coding.plugin.shutil.which", return_value="/usr/bin/git")
    @patch("zara_coding.plugin.unlock_worktree")
    @patch("zara_coding.plugin.lock_worktree")
    def test_plugin_exposes_approval_gated_worktree_lock_tools(self, lock, unlock, _which):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            target = root / "task-1"
            repo.mkdir()
            target.mkdir()
            lock.return_value = {
                "path": str(target.resolve()),
                "head": "a" * 40,
                "detached": True,
                "locked": "coding-task:17",
            }
            unlock.return_value = {
                "path": str(target.resolve()),
                "head": "a" * 40,
                "detached": True,
                "locked": None,
            }
            plugin = ZaraCodingPlugin()
            plugin.start(
                type(
                    "Runtime",
                    (),
                    {"configuration": {"plugins": {"zara-coding": {"allowed_roots": [str(root)]}}}},
                )()
            )
            tools = {tool.name: tool for tool in plugin.tools()}

            self.assertTrue(bool((tools["coding.git.worktree.lock"].metadata or {}).get("zara_requires_approval", False)))
            self.assertTrue(bool((tools["coding.git.worktree.unlock"].metadata or {}).get("zara_requires_approval", False)))
            locked = json.loads(plugin.git_worktree_lock(str(repo), str(target), "a" * 40, "coding-task:17"))
            unlocked = json.loads(plugin.git_worktree_unlock(str(repo), str(target), "a" * 40, "coding-task:17"))
            self.assertEqual(locked["locked"], "coding-task:17")
            self.assertIsNone(unlocked["locked"])
            lock.assert_called_once_with(plugin.inspector, repo, target, "a" * 40, "coding-task:17")
            unlock.assert_called_once_with(plugin.inspector, repo, target, "a" * 40, "coding-task:17")


if __name__ == "__main__":
    unittest.main()
