from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

langchain_core = types.ModuleType("langchain_core")
langchain_tools = types.ModuleType("langchain_core.tools")


class StructuredTool:
    @classmethod
    def from_function(cls, **kwargs):
        return kwargs


langchain_tools.StructuredTool = StructuredTool
langchain_core.tools = langchain_tools
sys.modules.setdefault("langchain_core", langchain_core)
sys.modules.setdefault("langchain_core.tools", langchain_tools)

zara = types.ModuleType("zara")
zara_plugins = types.ModuleType("zara.plugins")


class PluginMetadata:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class ServicePlugin:
    pass


zara_plugins.PluginMetadata = PluginMetadata
zara_plugins.ServicePlugin = ServicePlugin
zara.plugins = zara_plugins
sys.modules.setdefault("zara", zara)
sys.modules.setdefault("zara.plugins", zara_plugins)

from zara_context.plugin import ZaraContextPlugin
from zara_context.store import ContextError


class Runtime:
    def __init__(self, ttl):
        self.configuration = {
            "plugins": {"zara-context": {"default_ttl_seconds": ttl}}
        }


class ContextPluginConfigTest(unittest.TestCase):
    def test_rejects_coercive_default_ttl_descriptors(self):
        for value in ("10", True, None):
            with self.subTest(value=value):
                plugin = ZaraContextPlugin()
                with self.assertRaises(ContextError):
                    plugin.start(Runtime(value))

    def test_accepts_typed_numeric_default_ttl(self):
        plugin = ZaraContextPlugin()
        plugin.start(Runtime(2))
        item = plugin.publish_context(
            "file", {"path": "/tmp/a"}, source="test"
        )
        self.assertAlmostEqual(item.expires_at - item.observed_at, 2.0)


if __name__ == "__main__":
    unittest.main()
