import json
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

from zara_shell.plugin import ZaraShellPlugin, create_plugin


class Runtime:
    def __init__(self, configuration):
        self.configuration = configuration


class ShellPluginTests(unittest.TestCase):
    def test_factory_metadata_matches_registry_contract(self):
        plugin = create_plugin()
        self.assertEqual(plugin.metadata.name, "zara-shell")
        self.assertEqual(plugin.metadata.version, "0.1.0")
        self.assertEqual(plugin.metadata.api_version, "1")

    def test_shell_run_is_approval_required_by_construction(self):
        tools = {tool.name: tool for tool in ZaraShellPlugin().tools()}
        self.assertEqual(set(tools), {"shell.status", "shell.run"})
        self.assertIsNotNone(tools["shell.run"].metadata)
        self.assertIs(tools["shell.run"].metadata["zara_requires_approval"], True)
        self.assertFalse(bool((tools["shell.status"].metadata or {}).get("zara_requires_approval", False)))

    def test_unconfigured_plugin_fails_closed(self):
        plugin = ZaraShellPlugin()
        plugin.start(Runtime({"plugins": {"zara-shell": {}}}))
        status = json.loads(plugin.status())
        self.assertEqual(status["status"], "unavailable")
        self.assertEqual(status["reason"], "shell-policy-not-configured")
        with self.assertRaisesRegex(RuntimeError, "not configured"):
            plugin.run(["printf", "hello"], cwd="/")

    def test_configured_tool_uses_bounded_runner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plugin = ZaraShellPlugin()
            plugin.start(
                Runtime(
                    {
                        "plugins": {
                            "zara-shell": {
                                "allowed_programs": ["printf"],
                                "allowed_roots": [str(root)],
                                "allowed_environment": ["LANG"],
                                "max_runtime_seconds": 0.5,
                                "max_output_bytes": 64,
                                "max_input_bytes": 32,
                                "max_environment_bytes": 64,
                            }
                        }
                    }
                )
            )
            status = json.loads(plugin.status())
            self.assertEqual(status["allowed_environment_count"], 1)
            result = json.loads(
                plugin.run(["printf", "%s", "hello; echo nope"], cwd=str(root), env={"LANG": "C"})
            )
            self.assertEqual(result["exit_code"], 0)
            self.assertEqual(result["stdout"], "hello; echo nope")
            self.assertFalse(result["timed_out"])
            with self.assertRaisesRegex(RuntimeError, "environment variable is not allowed"):
                plugin.run(["printf", "ok"], cwd=str(root), env={"LD_PRELOAD": "/tmp/inject.so"})
            plugin.stop()
            self.assertEqual(json.loads(plugin.status())["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
