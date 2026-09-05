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
from zara_coding.worktree import add_detached_worktree


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


class WorktreeAddTests(unittest.TestCase):
    def test_domain_adds_detached_worktree_at_expected_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            target = root / "worktrees" / "task-1"
            calls = []

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                args = tuple(argv[3:])
                if args == ("rev-parse", "--show-toplevel"):
                    output = f"{repo.resolve()}\n"
                elif args == ("rev-parse", "--verify", f"{'a' * 40}^{{commit}}"):
                    output = f"{'a' * 40}\n"
                else:
                    output = ""
                return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            evidence = add_detached_worktree(inspector, repo, target, "a" * 40)

            self.assertEqual(evidence, {"path": str(target.resolve()), "head": "a" * 40, "detached": True})
            argv_calls = [call[0][3:] for call in calls]
            self.assertIn(["rev-parse", "--verify", f"{'a' * 40}^{{commit}}"], argv_calls)
            self.assertIn(["worktree", "add", "--detach", str(target.resolve()), "a" * 40], argv_calls)
            self.assertTrue(all(call[1]["shell"] is False for call in calls))

    def test_domain_rejects_existing_or_out_of_boundary_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            existing = root / "existing"
            existing.mkdir()
            inspector = RepositoryInspector((root,), runner=lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, stdout=f"{repo.resolve()}\n", stderr=""))

            with self.assertRaisesRegex(CodingError, "worktree target already exists"):
                add_detached_worktree(inspector, repo, existing, "a" * 40)
            with self.assertRaisesRegex(CodingError, "outside allowed roots"):
                add_detached_worktree(inspector, repo, root.parent / "outside-task", "a" * 40)

    def test_domain_rejects_non_commit_expected_object(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            target = root / "task"

            def run(argv, **kwargs):
                args = tuple(argv[3:])
                if args == ("rev-parse", "--show-toplevel"):
                    return subprocess.CompletedProcess(argv, 0, stdout=f"{repo.resolve()}\n", stderr="")
                if args and args[:2] == ("rev-parse", "--verify"):
                    raise subprocess.CalledProcessError(1, argv)
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "expected_head is not a commit"):
                add_detached_worktree(inspector, repo, target, "a" * 40)

    @patch("zara_coding.plugin.shutil.which", return_value="/usr/bin/git")
    @patch("zara_coding.plugin.add_detached_worktree")
    def test_plugin_worktree_add_requires_canonical_approval(self, add_worktree, _which):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            target = root / "task"
            add_worktree.return_value = {"path": str(target.resolve()), "head": "b" * 40, "detached": True}
            plugin = ZaraCodingPlugin()
            plugin.start(type("Runtime", (), {"configuration": {"plugins": {"zara-coding": {"allowed_roots": [str(root)]}}}})())
            tools = {tool.name: tool for tool in plugin.tools()}
            self.assertTrue(bool((tools["coding.git.worktree.add-detached"].metadata or {}).get("zara_requires_approval", False)))
            evidence = json.loads(plugin.git_worktree_add_detached(str(repo), str(target), "b" * 40))
            self.assertEqual(evidence["path"], str(target.resolve()))
            add_worktree.assert_called_once_with(plugin.inspector, repo, target, "b" * 40)


if __name__ == "__main__":
    unittest.main()
