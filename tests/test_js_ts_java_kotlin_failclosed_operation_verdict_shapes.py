from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req-operation-verdict-shapes"
ACTIVATION_ID = "act:" + ("e" * 32)
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
            f"failclosed_operation_verdict_{module_name}",
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


CASES = (
    (JAVASCRIPT, JAVASCRIPT.JavaScriptExpertAdapterError),
    (TYPESCRIPT, TYPESCRIPT.TypeScriptExpertAdapterError),
    (JAVA, JAVA.JavaExpertAdapterError),
    (KOTLIN, KOTLIN.KotlinExpertAdapterError),
)


def _result(module, *, verdict: object) -> dict[str, object]:
    return {
        "protocol": module.PROTOCOL,
        "request_id": REQUEST_ID,
        "activation_id": ACTIVATION_ID,
        "expert_id": module.EXPERT_ID,
        "expert_version": module.PLUGIN_VERSION,
        "manifest_digest": module.MANIFEST_DIGEST,
        "expert_operation": EXPERT_OPERATION,
        "resolved_registry_generation": EXPECTED_GENERATION,
        "resolved_runtime_generation": EXPECTED_GENERATION,
        "verdict": verdict,
        "data": {},
        "evidence_refs": [],
        "usage": {"model_calls": 0},
        "effect_receipts": [],
    }


class FailClosedOperationVerdictShapeTests(unittest.TestCase):
    def test_unhashable_operation_fails_as_adapter_error_before_host_dispatch(self) -> None:
        for module, error_type in CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                plugin = module.create_plugin()
                with self.assertRaisesRegex(error_type, "unsupported-expert-operation"):
                    plugin.invoke(
                        REQUEST_ID,
                        ACTIVATION_ID,
                        [],
                        EXPECTED_GENERATION,
                        EXPECTED_GENERATION,
                        "{}",
                    )

    def test_unhashable_result_verdict_fails_as_adapter_error(self) -> None:
        for module, error_type in CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                with self.assertRaisesRegex(error_type, "invalid-expert-verdict"):
                    module._validate_result(
                        _result(module, verdict=[]),
                        request_id=REQUEST_ID,
                        activation_id=ACTIVATION_ID,
                        expert_operation=EXPERT_OPERATION,
                        registry_generation=EXPECTED_GENERATION,
                        runtime_generation=EXPECTED_GENERATION,
                    )


if __name__ == "__main__":
    unittest.main()
