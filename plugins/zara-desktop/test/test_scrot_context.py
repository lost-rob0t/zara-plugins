from __future__ import annotations

import base64
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

langchain_core = types.ModuleType("langchain_core")
langchain_messages = types.ModuleType("langchain_core.messages")
langchain_tools = types.ModuleType("langchain_core.tools")


class HumanMessage:
    def __init__(self, content, id=None):
        self.content = content
        self.id = id


class StructuredTool:
    @classmethod
    def from_function(cls, **kwargs):
        return kwargs


langchain_messages.HumanMessage = HumanMessage
langchain_tools.StructuredTool = StructuredTool
langchain_core.messages = langchain_messages
langchain_core.tools = langchain_tools
sys.modules.setdefault("langchain_core", langchain_core)
sys.modules.setdefault("langchain_core.messages", langchain_messages)
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

from zara_desktop.desktop import DesktopConfig, SystemDesktopBackend
from zara_desktop.plugin import ZaraDesktopPlugin


PNG = b"\x89PNG\r\n\x1a\n" + b"payload"


class Runtime:
    def __init__(self, enabled):
        self.configuration = {
            "plugins": {
                "zara-desktop": {
                    "applications": {},
                    "screenshot_backend": "scrot",
                    "screenshot_context_hook_enabled": enabled,
                    "screenshot_context_hook_priority": -321,
                }
            }
        }
        self.registrations = []

    def register_agent_loop_advice(self, kind, priority, callback):
        self.registrations.append((kind, priority, callback))
        return len(self.registrations)


class ScrotContextTest(unittest.TestCase):
    def test_scrot_uses_exact_argv_without_shell_and_reads_png_from_stdout(self):
        calls = []

        def runner(argv, **kwargs):
            calls.append((tuple(argv), kwargs))
            return subprocess.CompletedProcess(argv, 0, stdout=PNG, stderr=b"")

        backend = SystemDesktopBackend(runner=runner, screenshot_backend="scrot")
        with patch("zara_desktop.desktop.shutil.which", side_effect=lambda name: "/usr/bin/scrot" if name == "scrot" else None):
            result = backend.screenshot()

        self.assertEqual(result["status"], "ok")
        self.assertEqual(base64.b64decode(result["data_base64"]), PNG)
        argv, kwargs = calls[0]
        self.assertEqual(argv, ("scrot", "--silent", "--file", "-"))
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["timeout"], 5.0)

    def test_auto_prefers_grim_then_scrot_and_explicit_scrot_does_not_fall_through(self):
        backend = SystemDesktopBackend(
            runner=lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, stdout=PNG, stderr=b""),
            screenshot_backend="auto",
        )
        with patch("zara_desktop.desktop.shutil.which", side_effect=lambda name: f"/usr/bin/{name}" if name in {"grim", "scrot"} else None):
            self.assertEqual(backend.selected_screenshot_backend(), "grim")

        explicit = SystemDesktopBackend(screenshot_backend="scrot")
        with patch("zara_desktop.desktop.shutil.which", side_effect=lambda name: f"/usr/bin/{name}" if name == "grim" else None):
            self.assertIsNone(explicit.selected_screenshot_backend())

    def test_screenshot_hook_is_opt_in_ordered_and_injects_multimodal_user_content(self):
        plugin = ZaraDesktopPlugin()
        runtime = Runtime(enabled=True)
        plugin.start(runtime)
        self.assertEqual(len(runtime.registrations), 1)
        kind, priority, callback = runtime.registrations[0]
        self.assertEqual((kind, priority), ("before", -321))

        plugin._service.screenshot = lambda: {
            "status": "ok",
            "mime_type": "image/png",
            "size": len(PNG),
            "data_base64": base64.b64encode(PNG).decode("ascii"),
        }
        state = {"messages": [HumanMessage("what is on my screen?", id="u1")]}
        callback(None, None, state)

        content = state["messages"][-1].content
        self.assertEqual(content[0], {"type": "text", "text": "what is on my screen?"})
        self.assertEqual(content[1]["type"], "image_url")
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/png;base64,"))

        disabled = Runtime(enabled=False)
        ZaraDesktopPlugin().start(disabled)
        self.assertEqual(disabled.registrations, [])

    def test_desktop_config_rejects_unknown_screenshot_backend(self):
        with self.assertRaises(Exception):
            DesktopConfig.load({"plugins": {"zara-desktop": {"screenshot_backend": "shell"}}})


if __name__ == "__main__":
    unittest.main()
