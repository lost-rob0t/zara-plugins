from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req-strict-result-json"
ACTIVATION_ID = "act:" + ("e" * 32)
EXPERT_OPERATION = "inspect"
EXPECTED_GENERATION = 1
INPUT_JSON = json.dumps(
    {
        "source": "const value = 1;",
        "source_generation": "source:generation:1",
    }
)


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
            f"strict_result_serializer_{module_name}",
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


class _Runtime:
    def __init__(self, module):
        self.module = module
        self.requests: list[dict[str, object]] = []

    def resolve_capability(self, capability: str) -> str:
        if capability != "expert.invoke":
            raise AssertionError(f"unexpected capability: {capability}")
        return capability

    def invoke_capability(self, _handle: str, request: dict[str, object]):
        self.requests.append(request)
        return {
            "protocol": self.module.PROTOCOL,
            "request_id": request["request_id"],
            "invocation_id": "inv:" + ("0" * 32),
            "activation_id": request["activation_id"],
            "expert_id": self.module.EXPERT_ID,
            "expert_version": self.module.PLUGIN_VERSION,
            "manifest_digest": self.module.MANIFEST_DIGEST,
            "expert_operation": request["expert_operation"],
            "resolved_registry_generation": request["expected_registry_generation"],
            "resolved_runtime_generation": request["expected_runtime_generation"],
            "verdict": "succeeded",
            "data": {"result": {}},
            "evidence_refs": [],
            "usage": {"model_calls": 0},
            "effect_receipts": [],
        }


def _plugin(module) -> tuple[object, _Runtime]:
    runtime = _Runtime(module)
    plugin = module.create_plugin()
    plugin.start(runtime)
    return plugin, runtime


def _invoke(module) -> tuple[str, _Runtime]:
    plugin, runtime = _plugin(module)
    encoded = plugin.invoke(
        REQUEST_ID,
        ACTIVATION_ID,
        EXPERT_OPERATION,
        EXPECTED_GENERATION,
        EXPECTED_GENERATION,
        INPUT_JSON,
    )
    return encoded, runtime


class StrictResultSerializerTests(unittest.TestCase):
    def test_strict_serializer_rejects_non_finite_and_cyclic_values(self) -> None:
        cycle: dict[str, object] = {}
        cycle["self"] = cycle
        for module, _error_type in CASES:
            plugin = module.create_plugin()
            with self.subTest(expert_id=module.EXPERT_ID, case="nan"):
                with self.assertRaises(ValueError):
                    plugin._json({"probe": float("nan")})
            with self.subTest(expert_id=module.EXPERT_ID, case="cycle"):
                with self.assertRaises((ValueError, RecursionError)):
                    plugin._json({"probe": cycle})

    def test_final_serializer_errors_fail_closed_after_valid_result_validation(self) -> None:
        for module, error_type in CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                plugin, runtime = _plugin(module)

                def fail_serializer(_value: object) -> str:
                    raise ValueError("strict serializer probe")

                plugin._json = fail_serializer
                with self.assertRaisesRegex(error_type, "invalid-expert-result-json"):
                    plugin.invoke(
                        REQUEST_ID,
                        ACTIVATION_ID,
                        EXPERT_OPERATION,
                        EXPECTED_GENERATION,
                        EXPECTED_GENERATION,
                        INPUT_JSON,
                    )
                self.assertEqual(len(runtime.requests), 1)
                self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)

    def test_canonical_result_remains_strict_json_and_zero_model(self) -> None:
        def reject_constant(value: str) -> None:
            raise AssertionError(f"non-finite JSON constant escaped serializer: {value}")

        for module, _error_type in CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                encoded, runtime = _invoke(module)
                decoded = json.loads(encoded, parse_constant=reject_constant)
                self.assertEqual(decoded["usage"], {"model_calls": 0})
                self.assertEqual(decoded["effect_receipts"], [])
                self.assertEqual(len(runtime.requests), 1)
                self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)


if __name__ == "__main__":
    unittest.main()
