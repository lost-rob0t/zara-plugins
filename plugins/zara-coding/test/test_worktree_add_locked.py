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
from zara_coding.worktree import add_detached_locked_worktree


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


class WorktreeAddLockedTests(unittest.TestCase):
    def test_add_locked_creates_exact_detached_worktree_then_locks_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            target = root / "worktrees" / "task-17"
            target.parent.mkdir()
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
                else:
                    output = ""
                return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            evidence = add_detached_locked_worktree(
                inspector,
                repo,
                target,
                "a" * 40,
                "coding-task:17",
            )

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
            add_index = argv_calls.index(["worktree", "add", "--detach", str(target.resolve()), "a" * 40])
            lock_index = argv_calls.index(
                ["worktree", "lock", "--reason", "coding-task:17", str(target.resolve())]
            )
            self.assertLess(add_index, lock_index)
            self.assertTrue(all(call[1]["shell"] is False for call in calls))

    def test_add_locked_rolls_back_clean_created_worktree_when_lock_command_fails(self):
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
                    return subprocess.CompletedProcess(argv, 0, stdout=f"{repo.resolve()}\n", stderr="")
                if args == ("rev-parse", "--verify", f"{'a' * 40}^{{commit}}"):
                    return subprocess.CompletedProcess(argv, 0, stdout=f"{'a' * 40}\n", stderr="")
                if args == ("worktree", "list", "--porcelain", "-z"):
                    return subprocess.CompletedProcess(
                        argv,
                        0,
                        stdout=(
                            f"worktree {repo.resolve()}\0HEAD {'b' * 40}\0branch refs/heads/main\0\0"
                            f"worktree {target.resolve()}\0HEAD {'a' * 40}\0detached\0\0"
                        ),
                        stderr="",
                    )
                if args == ("worktree", "lock", "--reason", "coding-task:17", str(target.resolve())):
                    raise subprocess.CalledProcessError(1, argv)
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "lock failed"):
                add_detached_locked_worktree(inspector, repo, target, "a" * 40, "coding-task:17")

            argv_calls = [call[0][3:] for call in calls]
            self.assertIn(["worktree", "remove", str(target.resolve())], argv_calls)
            self.assertNotIn(["worktree", "remove", "--force", str(target.resolve())], argv_calls)

    def test_add_locked_reports_lock_failure_without_deleting_changed_identity(self):
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
                    return subprocess.CompletedProcess(argv, 0, stdout=f"{repo.resolve()}\n", stderr="")
                if args == ("rev-parse", "--verify", f"{'a' * 40}^{{commit}}"):
                    return subprocess.CompletedProcess(argv, 0, stdout=f"{'a' * 40}\n", stderr="")
                if args == ("worktree", "list", "--porcelain", "-z"):
                    return subprocess.CompletedProcess(
                        argv,
                        0,
                        stdout=(
                            f"worktree {repo.resolve()}\0HEAD {'b' * 40}\0branch refs/heads/main\0\0"
                            f"worktree {target.resolve()}\0HEAD {'c' * 40}\0detached\0\0"
                        ),
                        stderr="",
                    )
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "rollback could not safely remove"):
                add_detached_locked_worktree(inspector, repo, target, "a" * 40, "coding-task:17")

            argv_calls = [call[0][3:] for call in calls]
            self.assertNotIn(["worktree", "remove", str(target.resolve())], argv_calls)
            self.assertNotIn(["worktree", "remove", "--force", str(target.resolve())], argv_calls)

    @patch("zara_coding.plugin.shutil.which", return_value="/usr/bin/git")
    @patch("zara_coding.plugin.add_detached_locked_worktree")
    def test_plugin_add_locked_is_one_approval_gated_mutation(self, add_locked, _which):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            target = root / "task-17"
            add_locked.return_value = {
                "path": str(target.resolve()),
                "head": "a" * 40,
                "detached": True,
                "locked": "coding-task:17",
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
            tool = tools["coding.git.worktree.add-detached-locked"]
            self.assertTrue(bool((tool.metadata or {}).get("zara_requires_approval", False)))

            evidence = json.loads(
                plugin.git_worktree_add_detached_locked(
                    str(repo),
                    str(target),
                    "a" * 40,
                    "coding-task:17",
                )
            )
            self.assertEqual(evidence["locked"], "coding-task:17")
            add_locked.assert_called_once_with(
                plugin.inspector,
                repo,
                target,
                "a" * 40,
                "coding-task:17",
            )


if __name__ == "__main__":
    unittest.main()
