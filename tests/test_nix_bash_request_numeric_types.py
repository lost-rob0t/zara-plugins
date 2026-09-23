from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req:nix-bash-request-numeric-types"
ACTIVATION_ID = "act:" + ("e" * 32)


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
            f"request_numeric_types_{module_name}",
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


class _ForgedInt(int):
    """Integer-shaped authority value with caller-controlled normalization."""

    def __new__(cls, value: int, normalized: int):
        instance = int.__new__(cls, value)
        instance.normalized = normalized
        return instance

    def __int__(self) -> int:
        return self.normalized


class _NoDispatchRuntime:
    def resolve_capability(self, capability: str):
        raise AssertionError(
            f"noncanonical numeric input must fail before host resolution: {capability}"
        )

    def invoke_capability(self, _handle, _request):
        raise AssertionError("noncanonical numeric input must fail before host invocation")


class RequestNumericTypeFenceTests(unittest.TestCase):
    @staticmethod
    def _adapter_error(module):
        return (
            module.NixExpertAdapterError
            if module is NIX
            else module.BashExpertAdapterError
        )

    def _invoke(self, module, **overrides) -> None:
        arguments = {
            "request_id": REQUEST_ID,
            "activation_id": ACTIVATION_ID,
            "expert_operation": "inspect",
            "expected_registry_generation": 1,
            "expected_runtime_generation": 1,
            "input_json": json.dumps(
                {"source": "x = 1", "source_generation": "fixture:1"}
            ),
            "timeout_ms": 1000,
            "max_results": 8,
            "max_output_bytes": 4096,
        }
        arguments.update(overrides)
        plugin = module.create_plugin()
        plugin.start(_NoDispatchRuntime())
        plugin.invoke(**arguments)

    def _assert_module_rejects_noncanonical_numbers(self, module) -> None:
        adapter_error = self._adapter_error(module)
        cases = (
            ("expected_registry_generation", 1.0, "invalid-registry-generation"),
            ("expected_registry_generation", _ForgedInt(9, 1), "invalid-registry-generation"),
            ("expected_runtime_generation", 1.0, "invalid-runtime-generation"),
            ("expected_runtime_generation", _ForgedInt(9, 1), "invalid-runtime-generation"),
            ("timeout_ms", 1000.0, "invalid-timeout-ms"),
            ("timeout_ms", _ForgedInt(999999, 1000), "invalid-timeout-ms"),
            ("max_results", 8.0, "invalid-max-results"),
            ("max_results", _ForgedInt(999999, 8), "invalid-max-results"),
            ("max_output_bytes", 4096.0, "invalid-max-output-bytes"),
            ("max_output_bytes", _ForgedInt(999999, 4096), "invalid-max-output-bytes"),
        )
        for field, value, message in cases:
            with self.subTest(module=module.__name__, field=field, value_type=type(value).__name__):
                with self.assertRaisesRegex(adapter_error, message):
                    self._invoke(module, **{field: value})

    def test_nix_rejects_noncanonical_authority_and_budget_numbers(self) -> None:
        self._assert_module_rejects_noncanonical_numbers(NIX)

    def test_bash_rejects_noncanonical_authority_and_budget_numbers(self) -> None:
        self._assert_module_rejects_noncanonical_numbers(BASH)


if __name__ == "__main__":
    unittest.main()
