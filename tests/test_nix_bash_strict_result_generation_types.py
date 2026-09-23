from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req-generation-type"
ACTIVATION_ID = "act:" + ("c" * 32)
INVOCATION_ID = "inv:" + ("d" * 32)
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
            f"strict_result_generation_{module_name}",
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


def _result(
    *,
    module,
    registry_generation: object = EXPECTED_GENERATION,
    runtime_generation: object = EXPECTED_GENERATION,
) -> dict[str, object]:
    return {
        "protocol": module.PROTOCOL,
        "request_id": REQUEST_ID,
        "invocation_id": INVOCATION_ID,
        "activation_id": ACTIVATION_ID,
        "expert_id": module.EXPERT_ID,
        "expert_version": module.PLUGIN_VERSION,
        "manifest_digest": module.MANIFEST_DIGEST,
        "expert_operation": EXPERT_OPERATION,
        "resolved_registry_generation": registry_generation,
        "resolved_runtime_generation": runtime_generation,
        "verdict": "succeeded",
        "data": {"verdict": "clean"},
        "evidence_refs": [],
        "usage": {"model_calls": 0},
        "effect_receipts": [],
    }


class StrictResultGenerationTypeTests(unittest.TestCase):
    def _assert_boolean_generation_rejected(self, *, module) -> None:
        cases = (
            {"registry_generation": True},
            {"runtime_generation": True},
        )
        for mutation in cases:
            with self.subTest(expert_id=module.EXPERT_ID, mutation=mutation):
                result = _result(module=module, **mutation)
                with self.assertRaisesRegex(
                    module.NixExpertAdapterError
                    if module is NIX
                    else module.BashExpertAdapterError,
                    "stale-expert-result",
                ):
                    module._validate_result(
                        result,
                        request_id=REQUEST_ID,
                        activation_id=ACTIVATION_ID,
                        expert_operation=EXPERT_OPERATION,
                        registry_generation=EXPECTED_GENERATION,
                        runtime_generation=EXPECTED_GENERATION,
                    )

    def test_nix_result_boolean_generations_fail_closed(self) -> None:
        self._assert_boolean_generation_rejected(module=NIX)

    def test_bash_result_boolean_generations_fail_closed(self) -> None:
        self._assert_boolean_generation_rejected(module=BASH)


if __name__ == "__main__":
    unittest.main()
