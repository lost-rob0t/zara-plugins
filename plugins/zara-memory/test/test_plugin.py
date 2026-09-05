import json
import sys
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

from zara_memory.plugin import ZaraMemoryPlugin, create_plugin


class MemoryPluginTests(unittest.TestCase):
    def test_factory_metadata_matches_registry_contract(self):
        plugin = create_plugin()
        self.assertEqual(plugin.metadata.name, "zara-memory")
        self.assertEqual(plugin.metadata.version, "0.1.0")
        self.assertEqual(plugin.metadata.api_version, "1")

    def test_default_service_degrades_honestly_without_backend(self):
        plugin = ZaraMemoryPlugin()
        status = json.loads(plugin.status())
        self.assertFalse(status["configured"])
        self.assertEqual(status["error"], "symbolic-memory-backend-not-configured")
        self.assertEqual(status["supported_scopes"], ["global", "machine", "project", "session", "user"])

    def test_default_service_lifecycle_is_safe_without_backend(self):
        plugin = ZaraMemoryPlugin()
        plugin.start(type("Runtime", (), {"configuration": {}})())
        plugin.stop()

    def test_only_safe_status_tool_is_published_without_backend_binding(self):
        plugin = ZaraMemoryPlugin()
        self.assertEqual([tool.name for tool in plugin.tools()], ["memory.status"])


if __name__ == "__main__":
    unittest.main()
