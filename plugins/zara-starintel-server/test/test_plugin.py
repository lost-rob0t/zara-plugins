import json
import os
import sys
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

from zara_starintel_server.client import StarIntelError
from zara_starintel_server.plugin import ZaraStarIntelServerPlugin


class FakeClient:
    def __init__(self):
        self.calls = []

    def request(self, method, path, *, query=None, body=None, headers=None):
        self.calls.append(("request", method, path, query, body, headers))
        return {"status": 200, "ok": True, "data": {"path": path}}

    def capabilities(self):
        self.calls.append(("capabilities",))
        return {"features": {"documents": True}, "endpoints": []}

    def operations(self, *, refresh=False):
        self.calls.append(("operations", refresh))
        return [{"operation_id": "health.get"}]

    def call_operation(
        self,
        operation_id,
        *,
        path_parameters=None,
        query=None,
        body=None,
        headers=None,
    ):
        self.calls.append(
            (
                "call_operation",
                operation_id,
                path_parameters,
                query,
                body,
                headers,
            )
        )
        return {"status": 200, "ok": True, "data": {"operation": operation_id}}


class Runtime:
    def __init__(self, configuration):
        self.configuration = configuration


class ZaraStarIntelServerPluginTest(unittest.TestCase):
    def test_registers_discovery_operation_and_generic_tools(self):
        plugin = ZaraStarIntelServerPlugin()
        tools = plugin.tools()
        self.assertEqual(
            [tool.name for tool in tools],
            [
                "starintel_status",
                "starintel_capabilities",
                "starintel_api_operations",
                "starintel_call_operation",
                "starintel_api_request",
            ],
        )
        self.assertIn("destructive", tools[-1].description.lower())

    def test_start_loads_secret_safe_configuration(self):
        environment = {
            "ZARA_STARINTEL_API_KEY": "api-secret",
            "ZARA_STARINTEL_BOOTSTRAP_SECRET": "bootstrap-secret",
        }
        with patch.dict(os.environ, environment, clear=True):
            plugin = ZaraStarIntelServerPlugin()
            plugin.start(
                Runtime({"base_url": "https://starintel.example"})
            )

        status = json.loads(plugin.starintel_status(include_health=False))
        encoded = json.dumps(status)
        self.assertEqual(status["base_url"], "https://starintel.example")
        self.assertTrue(status["api_key_configured"])
        self.assertTrue(status["bootstrap_secret_configured"])
        self.assertNotIn("api-secret", encoded)
        self.assertNotIn("bootstrap-secret", encoded)

    def test_status_can_check_remote_health(self):
        plugin = ZaraStarIntelServerPlugin()
        plugin._config = plugin._config.__class__(
            base_url="https://starintel.example",
            api_key="secret",
        )
        client = FakeClient()
        plugin._client = client

        status = json.loads(plugin.starintel_status())

        self.assertEqual(status["health"]["status"], 200)
        self.assertEqual(client.calls, [("request", "GET", "/health", None, None, None)])

    def test_capabilities_and_operations_are_json(self):
        plugin = ZaraStarIntelServerPlugin()
        client = FakeClient()
        plugin._client = client

        capabilities = json.loads(plugin.starintel_capabilities())
        operations = json.loads(plugin.starintel_api_operations(refresh=True))

        self.assertTrue(capabilities["features"]["documents"])
        self.assertEqual(operations[0]["operation_id"], "health.get")
        self.assertEqual(
            client.calls,
            [("capabilities",), ("operations", True)],
        )

    def test_call_operation_parses_structured_json_arguments(self):
        plugin = ZaraStarIntelServerPlugin()
        client = FakeClient()
        plugin._client = client

        result = json.loads(
            plugin.starintel_call_operation(
                "document.update",
                path_parameters_json='{"id":"doc-1"}',
                query_json='{"tenant":"default"}',
                body_json='{"name":"updated"}',
                headers_json='{"Idempotency-Key":"request-1"}',
            )
        )

        self.assertEqual(result["data"]["operation"], "document.update")
        self.assertEqual(
            client.calls[0],
            (
                "call_operation",
                "document.update",
                {"id": "doc-1"},
                {"tenant": "default"},
                {"name": "updated"},
                {"Idempotency-Key": "request-1"},
            ),
        )

    def test_generic_request_exposes_all_supported_methods(self):
        plugin = ZaraStarIntelServerPlugin()
        client = FakeClient()
        plugin._client = client

        plugin.starintel_api_request(
            "DELETE",
            "/document/doc-1",
            query_json="{}",
            body_json="",
            headers_json="{}",
        )

        self.assertEqual(
            client.calls,
            [("request", "DELETE", "/document/doc-1", {}, None, {})],
        )

    def test_mapping_arguments_reject_non_objects(self):
        plugin = ZaraStarIntelServerPlugin()
        with self.assertRaisesRegex(StarIntelError, "query_json"):
            plugin.starintel_api_request(
                "GET",
                "/search",
                query_json="[]",
            )


if __name__ == "__main__":
    unittest.main()
