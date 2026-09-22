from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req:nix-bash-duplicate-json-keys"
ACTIVATION_ID = "act:" + ("d" * 32)


class _PluginMetadata:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _ServicePlugin:
    pass


class _StructuredTool:
    pass


def _load_plugin(package: str, module_name: str):
    dependency_names = (
        "langchain_core",
        "langchain_core.tools",
        "zara",
        "zara.plugins",
    )
    previous = {name: sys.modules.get(name) for name in dependency_names}

    langchain_core = types.ModuleType("langchain_core")
    langchain_tools = types.ModuleType("langchain_core.tools")
    langchain_tools.StructuredTool = _StructuredTool
    langchain_core.tools = langchain_tools

    zara = types.ModuleType("zara")
    zara_plugins = types.ModuleType("zara.plugins")
    zara_plugins.PluginMetadata = _PluginMetadata
    zara_plugins.ServicePlugin = _ServicePlugin
    zara.plugins = zara_plugins

    sys.modules["langchain_core"] = langchain_core
    sys.modules["langchain_core.tools"] = langchain_tools
    sys.modules["zara"] = zara
    sys.modules["zara.plugins"] = zara_plugins

    try:
        path = REPO_ROOT / "plugins" / package / "lib" / module_name / "plugin.py"
        spec = importlib.util.spec_from_file_location(
            f"duplicate_json_keys_{module_name}",
            path,
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, value in previous.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


NIX = _load_plugin("zara-nix-expert", "zara_nix_expert")
BASH = _load_plugin("zara-bash-expert", "zara_bash_expert")


class _NoDispatchRuntime:
    def resolve_capability(self, capability: str):
        raise AssertionError(
            f"ambiguous JSON must fail before host resolution: {capability}"
        )

    def invoke_capability(self, _handle, _request):
        raise AssertionError("ambiguous JSON must fail before host invocation")


class DuplicateJsonKeyFenceTests(unittest.TestCase):
    @staticmethod
    def _adapter_error(module):
        return (
            module.NixExpertAdapterError
            if module is NIX
            else module.BashExpertAdapterError
        )

    def _assert_module_rejects_duplicate_keys(self, module, input_json: str) -> None:
        plugin = module.create_plugin()
        plugin.start(_NoDispatchRuntime())
        adapter_error = self._adapter_error(module)

        with self.assertRaisesRegex(adapter_error, "ambiguous-input-json"):
            plugin.invoke(
                request_id=REQUEST_ID,
                activation_id=ACTIVATION_ID,
                expert_operation="parse",
                expected_registry_generation=1,
                expected_runtime_generation=1,
                input_json=input_json,
                timeout_ms=1000,
                max_results=8,
                max_output_bytes=4096,
            )

    def test_nix_rejects_duplicate_top_level_keys_before_dispatch(self) -> None:
        self._assert_module_rejects_duplicate_keys(
            NIX,
            '{"source":"x = 1","source":"x = 2"}',
        )

    def test_bash_rejects_duplicate_top_level_keys_before_dispatch(self) -> None:
        self._assert_module_rejects_duplicate_keys(
            BASH,
            '{"source":"echo safe","source":"echo unsafe"}',
        )

    def test_nix_rejects_duplicate_nested_keys_before_dispatch(self) -> None:
        self._assert_module_rejects_duplicate_keys(
            NIX,
            '{"source":"x = 1","meta":{"path":"safe","path":"other"}}',
        )

    def test_bash_rejects_duplicate_nested_keys_before_dispatch(self) -> None:
        self._assert_module_rejects_duplicate_keys(
            BASH,
            '{"source":"echo safe","meta":{"path":"safe","path":"other"}}',
        )


if __name__ == "__main__":
    unittest.main()
