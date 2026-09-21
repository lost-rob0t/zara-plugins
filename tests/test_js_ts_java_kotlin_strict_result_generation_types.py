from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req-generation-type"
ACTIVATION_ID = "act:" + ("d" * 32)
EXPERT_OPERATION = "inspect"
EXPECTED_GENERATION = 1


class _PluginMetadata:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _ServicePlugin:
    pass


def _load_plugin(package: str, module_name: str):
    dependency_names = ("zara", "zara.plugins")
    previous = {name: sys.modules.get(name) for name in dependency_names}

    zara = types.ModuleType("zara")
    zara_plugins = types.ModuleType("zara.plugins")
    zara_plugins.PluginMetadata = _PluginMetadata
    zara_plugins.ServicePlugin = _ServicePlugin
    zara.plugins = zara_plugins

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


JAVASCRIPT = _load_plugin("zara-javascript-expert", "zara_javascript_expert")
TYPESCRIPT = _load_plugin("zara-typescript-expert", "zara_typescript_expert")
JAVA = _load_plugin("zara-java-expert", "zara_java_expert")
KOTLIN = _load_plugin("zara-kotlin-expert", "zara_kotlin_expert")


def _result(
    module,
    *,
    registry_generation: object = EXPECTED_GENERATION,
    runtime_generation: object = EXPECTED_GENERATION,
) -> dict[str, object]:
    return {
        "protocol": module.PROTOCOL,
        "request_id": REQUEST_ID,
        "activation_id": ACTIVATION_ID,
        "expert_id": module.EXPERT_ID,
        "expert_version": module.PLUGIN_VERSION,
        "manifest_digest": module.MANIFEST_DIGEST,
        "expert_operation": EXPERT_OPERATION,
        "resolved_registry_generation": registry_generation,
        "resolved_runtime_generation": runtime_generation,
        "verdict": "succeeded",
        "data": {"ok": True},
        "usage": {"model_calls": 0},
        "effect_receipts": [],
    }


class StrictResultGenerationTypeTests(unittest.TestCase):
    def _assert_boolean_generation_rejected(self, *, module, error_type) -> None:
        cases = (
            {"registry_generation": True},
            {"runtime_generation": True},
        )
        for mutation in cases:
            with self.subTest(expert_id=module.EXPERT_ID, mutation=mutation):
                with self.assertRaisesRegex(error_type, "stale-expert-result"):
                    module._validate_result(
                        _result(module, **mutation),
                        request_id=REQUEST_ID,
                        activation_id=ACTIVATION_ID,
                        expert_operation=EXPERT_OPERATION,
                        registry_generation=EXPECTED_GENERATION,
                        runtime_generation=EXPECTED_GENERATION,
                    )

    def test_javascript_boolean_result_generations_fail_closed(self) -> None:
        self._assert_boolean_generation_rejected(
            module=JAVASCRIPT,
            error_type=JAVASCRIPT.JavaScriptExpertAdapterError,
        )

    def test_typescript_boolean_result_generations_fail_closed(self) -> None:
        self._assert_boolean_generation_rejected(
            module=TYPESCRIPT,
            error_type=TYPESCRIPT.TypeScriptExpertAdapterError,
        )

    def test_java_boolean_result_generations_fail_closed(self) -> None:
        self._assert_boolean_generation_rejected(
            module=JAVA,
            error_type=JAVA.JavaExpertAdapterError,
        )

    def test_kotlin_boolean_result_generations_fail_closed(self) -> None:
        self._assert_boolean_generation_rejected(
            module=KOTLIN,
            error_type=KOTLIN.KotlinExpertAdapterError,
        )


if __name__ == "__main__":
    unittest.main()
