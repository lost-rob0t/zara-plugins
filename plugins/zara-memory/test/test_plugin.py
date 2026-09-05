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

from zara_memory.plugin import ZaraMemoryPlugin, create_plugin


class Runtime:
    def __init__(self, configuration):
        self.configuration = configuration


class FakeNativeClient:
    def remember(self, text, *, scope, retention, kind):
        return {"status": "stored", "id": "mem_1", "durable": True, "projection_status": "not_attempted"}

    def get(self, memory_id):
        return {"id": memory_id, "source_text": "hello", "lifecycle": "active"}


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
        self.assertEqual(status["native_supported_scopes"], ["global", "project", "session"])

    def test_native_tools_are_fail_closed_and_write_requires_core_approval(self):
        tools = {tool.name: tool for tool in ZaraMemoryPlugin().tools()}
        self.assertEqual(set(tools), {"memory.status", "memory.remember", "memory.get"})
        self.assertIs(tools["memory.remember"].metadata["zara_requires_approval"], True)
        self.assertFalse(bool((tools["memory.get"].metadata or {}).get("zara_requires_approval", False)))
        with self.assertRaisesRegex(RuntimeError, "backend-not-configured"):
            ZaraMemoryPlugin().remember("hello")

    def test_injected_native_client_preserves_backend_evidence(self):
        plugin = ZaraMemoryPlugin(native_client=FakeNativeClient())
        stored = json.loads(plugin.remember("hello", scope="project", retention="long_term", kind="text"))
        fetched = json.loads(plugin.get("mem_1"))
        self.assertEqual(stored["id"], "mem_1")
        self.assertEqual(stored["projection_status"], "not_attempted")
        self.assertEqual(fetched["source_text"], "hello")

    @patch("zara_memory.plugin.shutil.which", return_value="/run/current-system/sw/bin/symbolic-memory-mcp")
    def test_runtime_configuration_binds_native_backend_without_model_authority_fields(self, _which):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "memory.db"
            plugin = ZaraMemoryPlugin()
            plugin.start(Runtime({
                "plugins": {
                    "zara-memory": {
                        "symbolic_memory": {
                            "executable": "symbolic-memory-mcp",
                            "database": str(database),
                            "principal": "zara-local",
                            "session_id": "session-1",
                            "project_remote": "https://git.example/repo.git",
                            "capabilities": ["memory_read", "memory_write_project"],
                        }
                    }
                }
            }))
            status = json.loads(plugin.status())
            self.assertTrue(status["configured"])
            self.assertEqual(status["backend"], "symbolic-memory-mcp")

    @patch("zara_memory.plugin.shutil.which", return_value=None)
    def test_missing_native_executable_degrades_honestly(self, _which):
        plugin = ZaraMemoryPlugin()
        plugin.start(Runtime({
            "plugins": {"zara-memory": {"symbolic_memory": {
                "executable": "symbolic-memory-mcp",
                "database": "/var/lib/zara/memory.db",
                "principal": "zara-local",
                "session_id": "s1",
                "capabilities": ["memory_read"],
            }}}
        }))
        status = json.loads(plugin.status())
        self.assertFalse(status["configured"])
        self.assertEqual(status["error"], "symbolic-memory-executable-not-found")

    def test_rejects_mutable_database_path_in_nix_store(self):
        plugin = ZaraMemoryPlugin()
        with self.assertRaisesRegex(ValueError, "Nix store"):
            plugin.start(Runtime({
                "plugins": {"zara-memory": {"symbolic_memory": {
                    "executable": "/bin/true",
                    "database": "/nix/store/deadbeef-memory.db",
                    "principal": "zara-local",
                    "session_id": "s1",
                    "capabilities": ["memory_read"],
                }}}
            }))


if __name__ == "__main__":
    unittest.main()
