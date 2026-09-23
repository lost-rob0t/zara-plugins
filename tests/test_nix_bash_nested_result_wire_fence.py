from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req-nested-result-wire-fence"
ACTIVATION_ID = "act:" + ("d" * 32)
INVOCATION_ID = "inv:" + ("b" * 32)
EXPERT_OPERATION = "inspect"
EXPECTED_GENERATION = 1


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
            f"nested_result_wire_fence_{module_name}",
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


class _DeceptiveData(dict[str, object]):
    """Validate as clean data, then inject provider-shaped state on encoding."""

    def __init__(self) -> None:
        super().__init__({"verdict": "clean"})
        self._items_calls = 0

    def items(self):
        self._items_calls += 1
        if self._items_calls == 1:
            return [("verdict", "clean")]
        return [("provider_fallback", True)]


def _canonical_result(module) -> dict[str, object]:
    return {
        "protocol": "ZARA-EXPERT/1",
        "request_id": REQUEST_ID,
        "invocation_id": INVOCATION_ID,
        "activation_id": ACTIVATION_ID,
        "expert_id": module.EXPERT_ID,
        "expert_version": module.PLUGIN_VERSION,
        "manifest_digest": module.MANIFEST_DIGEST,
        "expert_operation": EXPERT_OPERATION,
        "resolved_registry_generation": EXPECTED_GENERATION,
        "resolved_runtime_generation": EXPECTED_GENERATION,
        "verdict": "succeeded",
        "data": _DeceptiveData(),
        "evidence_refs": ["source:fixture"],
        "usage": {"model_calls": 0},
        "effect_receipts": [],
    }


class _Runtime:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result

    def resolve_capability(self, capability: str) -> str:
        if capability != "expert.invoke":
            raise AssertionError(capability)
        return capability

    def invoke_capability(self, handle: str, request: dict[str, object]) -> dict[str, object]:
        if handle != "expert.invoke":
            raise AssertionError(handle)
        limits = request["limits"]
        if not isinstance(limits, dict) or limits.get("max_model_calls") != 0:
            raise AssertionError("pure-symbolic invocation must keep max_model_calls=0")
        return self.result


class NestedResultWireFenceTests(unittest.TestCase):
    @staticmethod
    def _adapter_error(module):
        return (
            module.NixExpertAdapterError
            if module is NIX
            else module.BashExpertAdapterError
        )

    def _assert_deceptive_data_rejected(self, module) -> None:
        plugin = module.create_plugin()
        plugin.start(_Runtime(_canonical_result(module)))
        adapter_error = self._adapter_error(module)

        with self.assertRaisesRegex(adapter_error, "invalid-expert-data"):
            plugin.invoke(
                request_id=REQUEST_ID,
                activation_id=ACTIVATION_ID,
                expert_operation=EXPERT_OPERATION,
                expected_registry_generation=EXPECTED_GENERATION,
                expected_runtime_generation=EXPECTED_GENERATION,
                input_json=json.dumps(
                    {"source": "x = 1", "source_generation": "fixture:1"}
                ),
            )

    def test_nix_rejects_mutating_data_dict_subclass_before_projection(self) -> None:
        self._assert_deceptive_data_rejected(NIX)

    def test_bash_rejects_mutating_data_dict_subclass_before_projection(self) -> None:
        self._assert_deceptive_data_rejected(BASH)


if __name__ == "__main__":
    unittest.main()
