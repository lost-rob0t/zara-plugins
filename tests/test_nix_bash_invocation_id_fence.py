from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req-invocation-id-fence"
ACTIVATION_ID = "act:" + ("d" * 32)
INVOCATION_ID = "inv:" + ("a" * 32)
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
            f"invocation_id_fence_{module_name}",
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


def _result(module) -> dict[str, object]:
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
        "data": {"result": {}},
        "evidence_refs": ["source:fixture"],
        "usage": {"model_calls": 0},
        "effect_receipts": [],
    }


class InvocationIdFenceTests(unittest.TestCase):
    def _validate(self, module, result: dict[str, object]) -> None:
        module._validate_result(
            result,
            request_id=REQUEST_ID,
            activation_id=ACTIVATION_ID,
            expert_operation=EXPERT_OPERATION,
            registry_generation=EXPECTED_GENERATION,
            runtime_generation=EXPECTED_GENERATION,
        )

    def _assert_invocation_id_fence(self, module) -> None:
        self._validate(module, _result(module))

        adapter_error = (
            module.NixExpertAdapterError
            if module is NIX
            else module.BashExpertAdapterError
        )
        invalid_ids: tuple[object, ...] = (
            None,
            7,
            "",
            "inv:short",
            "inv:" + ("g" * 32),
            "inv:" + ("a" * 33),
        )
        for invocation_id in invalid_ids:
            with self.subTest(expert_id=module.EXPERT_ID, invocation_id=invocation_id):
                result = _result(module)
                result["invocation_id"] = invocation_id
                with self.assertRaisesRegex(
                    adapter_error,
                    "invalid-expert-invocation-id",
                ):
                    self._validate(module, result)

    def test_nix_rejects_noncanonical_core_invocation_ids(self) -> None:
        self._assert_invocation_id_fence(NIX)

    def test_bash_rejects_noncanonical_core_invocation_ids(self) -> None:
        self._assert_invocation_id_fence(BASH)


if __name__ == "__main__":
    unittest.main()
