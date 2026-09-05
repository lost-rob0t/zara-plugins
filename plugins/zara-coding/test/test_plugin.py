import json
import subprocess
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass
from pathlib import Path

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


zara = types.ModuleType("zara")
zara_plugins = types.ModuleType("zara.plugins")
zara_plugins.PluginMetadata = PluginMetadata
zara_plugins.ServicePlugin = ServicePlugin
sys.modules.setdefault("zara", zara)
sys.modules.setdefault("zara.plugins", zara_plugins)

from zara_coding.plugin import ZaraCodingPlugin, create_plugin


class Runtime:
    def __init__(self, configuration):
        self.configuration = configuration


class CodingPluginTests(unittest.TestCase):
    def test_factory_metadata_matches_registry_contract(self):
        plugin = create_plugin()
        self.assertEqual(plugin.metadata.name, "zara-coding")
        self.assertEqual(plugin.metadata.version, "0.1.0")
        self.assertEqual(plugin.metadata.api_version, "1")

    def test_read_only_initial_surface_has_no_approval_bypass(self):
        tools = {tool.name: tool for tool in ZaraCodingPlugin().tools()}
        self.assertEqual(set(tools), {"coding.status", "coding.repo.inspect"})
        for tool in tools.values():
            self.assertFalse(bool((tool.metadata or {}).get("zara_requires_approval", False)))

    def test_unconfigured_plugin_loads_degraded_and_fails_repo_inspection_closed(self):
        plugin = ZaraCodingPlugin()
        plugin.start(Runtime({"plugins": {"zara-coding": {}}}))
        status = json.loads(plugin.status())
        self.assertEqual(status["status"], "degraded")
        self.assertEqual(status["repository"], {"status": "unavailable", "reason": "allowed-roots-not-configured"})
        self.assertEqual(status["prolog_rlm"], {"status": "unavailable", "reason": "prolog-rlm-checkout-not-configured"})
        with self.assertRaisesRegex(RuntimeError, "allowed_roots"):
            plugin.inspect_repo("/")

    def test_configured_plugin_returns_structured_repo_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Zara Plugin Test"], check=True)
            (repo / "file.txt").write_text("base\n")
            subprocess.run(["git", "-C", str(repo), "add", "file.txt"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
            plugin = ZaraCodingPlugin()
            plugin.start(Runtime({"plugins": {"zara-coding": {"allowed_roots": [str(root)]}}}))
            evidence = json.loads(plugin.inspect_repo(str(repo)))
            self.assertEqual(evidence["root"], str(repo.resolve()))
            self.assertEqual(len(evidence["head"]), 40)
            self.assertFalse(evidence["dirty"])


if __name__ == "__main__":
    unittest.main()
