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


zara = types.ModuleType("zara")
zara_plugins = types.ModuleType("zara.plugins")
zara_plugins.PluginMetadata = PluginMetadata
zara_plugins.ServicePlugin = ServicePlugin
sys.modules.setdefault("zara", zara)
sys.modules.setdefault("zara.plugins", zara_plugins)

from zara_pi.plugin import ZaraPiPlugin, create_plugin


class Runtime:
    def __init__(self, configuration):
        self.configuration = configuration


class PiPluginTests(unittest.TestCase):
    def test_factory_metadata_matches_registry_contract(self):
        plugin = create_plugin()
        self.assertEqual(plugin.metadata.name, "zara-pi")
        self.assertEqual(plugin.metadata.version, "0.1.0")
        self.assertEqual(plugin.metadata.api_version, "1")

    def test_effectful_bash_and_tmux_tools_require_canonical_approval(self):
        tools = {tool.name: tool for tool in ZaraPiPlugin().tools()}
        self.assertEqual(
            set(tools),
            {
                "pi.status",
                "pi.bash",
                "pi.tmux.ensure",
                "pi.tmux.capture",
                "pi.tmux.interrupt",
                "pi.tmux.close",
            },
        )
        self.assertFalse(bool((tools["pi.status"].metadata or {}).get("zara_requires_approval", False)))
        for name in set(tools) - {"pi.status"}:
            with self.subTest(name=name):
                self.assertIsNotNone(tools[name].metadata)
                self.assertIs(tools[name].metadata["zara_requires_approval"], True)
                schema = tools[name].args_schema.model_json_schema()
                self.assertNotIn("yolo", schema.get("properties", {}))
                self.assertNotIn("approval", schema.get("properties", {}))

    def test_unconfigured_plugin_fails_closed(self):
        plugin = ZaraPiPlugin()
        plugin.start(Runtime({"plugins": {"zara-pi": {}}}))
        status = json.loads(plugin.status())
        self.assertEqual(status["status"], "unavailable")
        self.assertEqual(status["reason"], "pi-policy-not-configured")
        with self.assertRaisesRegex(RuntimeError, "not configured"):
            plugin.bash("dev", "call-1", "pwd", "/tmp")

    def test_configured_status_reports_pi_tmux_and_bash_readiness_without_secrets(self):
        with tempfile.TemporaryDirectory() as temporary:
            plugin = ZaraPiPlugin()
            runtime = Runtime(
                {
                    "plugins": {
                        "zara-pi": {
                            "allowed_roots": [temporary],
                            "pi": "pi",
                            "tmux": "tmux",
                            "bash": "bash",
                            "max_command_bytes": 8192,
                            "max_capture_bytes": 4096,
                            "max_tmux_lines": 500,
                            "operation_timeout_seconds": 3.0,
                        }
                    }
                }
            )
            resolved = {
                "pi": "/usr/bin/pi",
                "tmux": "/usr/bin/tmux",
                "bash": "/usr/bin/bash",
            }
            with patch("zara_pi.plugin.shutil.which", side_effect=lambda name: resolved.get(name)):
                plugin.start(runtime)
                status = json.loads(plugin.status())
            self.assertEqual(status["status"], "ready")
            self.assertTrue(status["pi_available"])
            self.assertTrue(status["tmux_available"])
            self.assertTrue(status["bash_available"])
            self.assertEqual(status["allowed_root_count"], 1)
            self.assertEqual(status["max_command_bytes"], 8192)
            self.assertNotIn("environment", status)
            self.assertNotIn("api_key", json.dumps(status).lower())

    def test_missing_pi_is_degraded_but_does_not_disable_tmux_bridge(self):
        with tempfile.TemporaryDirectory() as temporary:
            plugin = ZaraPiPlugin()
            runtime = Runtime(
                {
                    "plugins": {
                        "zara-pi": {
                            "allowed_roots": [temporary],
                            "pi": "pi",
                            "tmux": "tmux",
                            "bash": "bash",
                        }
                    }
                }
            )
            resolved = {"tmux": "/usr/bin/tmux", "bash": "/usr/bin/bash"}
            with patch("zara_pi.plugin.shutil.which", side_effect=lambda name: resolved.get(name)):
                plugin.start(runtime)
                status = json.loads(plugin.status())
            self.assertEqual(status["status"], "degraded")
            self.assertFalse(status["pi_available"])
            self.assertTrue(status["tmux_available"])
            self.assertTrue(status["bash_available"])
            self.assertTrue(status["tmux_bridge_ready"])

    def test_scalar_configuration_collections_fail_closed(self):
        plugin = ZaraPiPlugin()
        with self.assertRaisesRegex(RuntimeError, "allowed_roots must be a list"):
            plugin.start(Runtime({"plugins": {"zara-pi": {"allowed_roots": "/tmp"}}}))


if __name__ == "__main__":
    unittest.main()
