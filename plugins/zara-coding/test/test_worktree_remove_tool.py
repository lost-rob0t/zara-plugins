import json
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))


@dataclass(frozen=True)
class PluginMetadata:
    name: str
    version: str = ""
    api_version: str = "1"
    description: str = ""


class ServicePlugin:
    pass


class StructuredTool:
    @classmethod
    def from_function(cls, *, func, name, description, metadata=None):
        tool = cls()
        tool.func = func
        tool.name = name
        tool.description = description
        tool.metadata = metadata or {}
        return tool


zara = types.ModuleType("zara")
zara_plugins = types.ModuleType("zara.plugins")
zara_plugins.PluginMetadata = PluginMetadata
zara_plugins.ServicePlugin = ServicePlugin
sys.modules.setdefault("zara", zara)
sys.modules.setdefault("zara.plugins", zara_plugins)
langchain_core = types.ModuleType("langchain_core")
langchain_tools = types.ModuleType("langchain_core.tools")
langchain_tools.StructuredTool = StructuredTool
sys.modules.setdefault("langchain_core", langchain_core)
sys.modules.setdefault("langchain_core.tools", langchain_tools)

from zara_coding.plugin import ZaraCodingPlugin


class WorktreeRemoveToolTests(unittest.TestCase):
    @patch("zara_coding.plugin.shutil.which", return_value="/usr/bin/git")
    @patch("zara_coding.plugin.remove_detached_worktree")
    def test_plugin_exposes_approval_gated_remove_with_exact_head(self, remove, _which):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            target = root / "task-1"
            repo.mkdir()
            target.mkdir()
            remove.return_value = {
                "path": str(target.resolve()),
                "head": "a" * 40,
                "removed": True,
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

            tool = tools["coding.git.worktree.remove-detached"]
            self.assertTrue(bool((tool.metadata or {}).get("zara_requires_approval", False)))
            evidence = json.loads(
                plugin.git_worktree_remove_detached(str(repo), str(target), "a" * 40)
            )
            self.assertTrue(evidence["removed"])
            remove.assert_called_once_with(plugin.inspector, repo, target, "a" * 40)


if __name__ == "__main__":
    unittest.main()
