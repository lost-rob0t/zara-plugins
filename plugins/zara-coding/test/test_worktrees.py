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

from zara_coding.domain import RepositoryInspector


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


class WorktreeInventoryTests(unittest.TestCase):
    def test_domain_returns_bounded_structured_worktree_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            calls = []

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                args = argv[3:]
                outputs = {
                    ("rev-parse", "--show-toplevel"): f"{repo.resolve()}\n",
                    ("worktree", "list", "--porcelain", "-z"): (
                        f"worktree {repo.resolve()}\0HEAD {'a' * 40}\0branch refs/heads/main\0\0"
                        f"worktree {root / 'feature'}\0HEAD {'b' * 40}\0branch refs/heads/feature\0locked maintenance\0\0"
                    ),
                }
                return subprocess.CompletedProcess(argv, 0, stdout=outputs.get(tuple(args), ""), stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            worktrees = inspector.worktrees(repo, limit=2)

            self.assertEqual(worktrees[0]["path"], str(repo.resolve()))
            self.assertEqual(worktrees[0]["branch"], "main")
            self.assertFalse(worktrees[0]["detached"])
            self.assertEqual(worktrees[1]["branch"], "feature")
            self.assertEqual(worktrees[1]["locked"], "maintenance")
            self.assertTrue(all(call[1]["shell"] is False for call in calls))

    def test_domain_rejects_unbounded_worktree_limit_before_listing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            inspector = RepositoryInspector((root,), runner=lambda *_args, **_kwargs: None)
            with self.assertRaisesRegex(ValueError, "between 1 and 100"):
                inspector.worktrees(repo, limit=101)

    @patch("zara_coding.plugin.shutil.which", return_value="/usr/bin/git")
    @patch("zara_coding.plugin.RepositoryInspector.worktrees")
    def test_plugin_exposes_read_only_worktree_inventory(self, worktrees, _which):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            worktrees.return_value = [{"path": str(repo.resolve()), "head": "a" * 40, "branch": "main", "detached": False, "locked": None, "prunable": None}]
            plugin = ZaraCodingPlugin()
            plugin.start(type("Runtime", (), {"configuration": {"plugins": {"zara-coding": {"allowed_roots": [str(root)]}}}})())
            tools = {tool.name: tool for tool in plugin.tools()}
            self.assertIn("coding.git.worktrees", tools)
            self.assertFalse(bool((tools["coding.git.worktrees"].metadata or {}).get("zara_requires_approval", False)))
            evidence = json.loads(plugin.git_worktrees(str(repo), limit=7))
            self.assertEqual(evidence[0]["branch"], "main")
            worktrees.assert_called_once_with(repo, limit=7)


if __name__ == "__main__":
    unittest.main()
