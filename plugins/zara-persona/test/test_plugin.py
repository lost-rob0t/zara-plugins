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


class FakeTool:
    def __init__(self, function, name, description):
        self.function = function
        self.name = name
        self.description = description


class StructuredTool:
    @classmethod
    def from_function(cls, *, func, name, description):
        return FakeTool(func, name, description)


langchain_core = types.ModuleType("langchain_core")
langchain_tools = types.ModuleType("langchain_core.tools")
langchain_tools.StructuredTool = StructuredTool
zara = types.ModuleType("zara")
zara_plugins = types.ModuleType("zara.plugins")
zara_plugins.PluginMetadata = PluginMetadata
zara_plugins.ServicePlugin = ServicePlugin
sys.modules.setdefault("langchain_core", langchain_core)
sys.modules.setdefault("langchain_core.tools", langchain_tools)
sys.modules.setdefault("zara", zara)
sys.modules.setdefault("zara.plugins", zara_plugins)

from zara_persona_service.plugin import ZaraPersonaPlugin


class Runtime:
    def __init__(self, configuration):
        self.configuration = configuration


class ZaraPersonaPluginLifecycleTest(unittest.TestCase):
    def test_start_and_stop_with_local_disabled_configuration(self):
        plugin = ZaraPersonaPlugin()
        plugin.start(Runtime({"enabled": False}))
        self.assertTrue(plugin._started)
        plugin.stop()


if __name__ == "__main__":
    unittest.main()
