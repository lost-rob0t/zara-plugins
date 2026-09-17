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
zara_context_api = types.ModuleType("zara.context")


class PluginMetadata:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class ServicePlugin:
    pass


def add_context_fragment(state, text, *, source, sensitivity=None):
    state.setdefault("fragments", []).append((source, text))


zara_plugins.PluginMetadata = PluginMetadata
zara_plugins.ServicePlugin = ServicePlugin
zara_context_api.add_context_fragment = add_context_fragment
zara.plugins = zara_plugins
zara.context = zara_context_api
sys.modules.setdefault("zara", zara)
sys.modules.setdefault("zara.plugins", zara_plugins)
sys.modules.setdefault("zara.context", zara_context_api)

from zara_context.plugin import ZaraContextPlugin
from zara_context.system import LinuxSystemContextProvider


class Runtime:
    def __init__(self, enabled=True, priority=-1000):
        self.configuration = {
            "plugins": {
                "zara-context": {
                    "default_ttl_seconds": 30,
                    "system_context_hook_enabled": enabled,
                    "system_context_hook_priority": priority,
                }
            }
        }
        self.registrations = []

    def register_agent_loop_advice(self, kind, priority, callback):
        self.registrations.append((kind, priority, callback))
        return len(self.registrations)


class SystemContextHookTest(unittest.TestCase):
    def test_provider_exposes_bounded_non_secret_linux_session_facts(self):
        provider = LinuxSystemContextProvider(
            environ={
                "XDG_SESSION_TYPE": "wayland",
                "XDG_CURRENT_DESKTOP": "qtile",
                "DESKTOP_SESSION": "qtile",
                "HOME": "/secret/home",
                "API_KEY": "nope",
            },
            uname=lambda: types.SimpleNamespace(
                system="Linux",
                release="6.12.1",
                machine="x86_64",
            ),
        )

        text = provider.render()

        self.assertIn("os=Linux", text)
        self.assertIn("session_type=wayland", text)
        self.assertIn("desktop=qtile", text)
        self.assertNotIn("/secret/home", text)
        self.assertNotIn("nope", text)
        self.assertLessEqual(len(text), 2048)

    def test_plugin_registers_before_hook_only_when_enabled(self):
        enabled_runtime = Runtime(enabled=True, priority=-432)
        plugin = ZaraContextPlugin()
        plugin.start(enabled_runtime)

        self.assertEqual(len(enabled_runtime.registrations), 1)
        kind, priority, callback = enabled_runtime.registrations[0]
        self.assertEqual((kind, priority), ("before", -432))
        state = {}
        callback(None, None, state)
        self.assertEqual(state["fragments"][0][0], "plugin:zara-context:linux-system")
        self.assertIn("os=", state["fragments"][0][1])

        disabled_runtime = Runtime(enabled=False)
        ZaraContextPlugin().start(disabled_runtime)
        self.assertEqual(disabled_runtime.registrations, [])

    def test_priority_must_be_bounded_integer(self):
        for priority in (True, "0", 100001, -100001):
            with self.subTest(priority=priority):
                with self.assertRaises(ValueError):
                    ZaraContextPlugin().start(Runtime(enabled=True, priority=priority))


if __name__ == "__main__":
    unittest.main()
