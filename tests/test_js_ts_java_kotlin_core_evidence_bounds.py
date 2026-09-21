from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req-core-evidence-bounds"
ACTIVATION_ID = "act:" + ("a" * 32)
EXPERT_OPERATION = "inspect"
EXPECTED_GENERATION = 1
CORE_MAX_EVIDENCE_REFS = 32
CORE_MAX_EVIDENCE_REF_LENGTH = 128
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
            f"core_evidence_bounds_{module_name}",
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
    def __init__(self, module, evidence_refs: list[str]):
        self.module = module
        self.evidence_refs = evidence_refs
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
            "activation_id": request["activation_id"],
            "expert_id": self.module.EXPERT_ID,
            "expert_version": self.module.PLUGIN_VERSION,
            "manifest_digest": self.module.MANIFEST_DIGEST,
            "expert_operation": request["expert_operation"],
            "resolved_registry_generation": request["expected_registry_generation"],
            "resolved_runtime_generation": request["expected_runtime_generation"],
            "verdict": "succeeded",
            "data": {"result": {}},
            "evidence_refs": self.evidence_refs,
            "usage": {"model_calls": 0},
            "effect_receipts": [],
        }


def _invoke(module, evidence_refs: list[str]) -> tuple[str, _Runtime]:
    runtime = _Runtime(module, evidence_refs)
    plugin = module.create_plugin()
    plugin.start(runtime)
    encoded = plugin.invoke(
        REQUEST_ID,
        ACTIVATION_ID,
        EXPERT_OPERATION,
        EXPECTED_GENERATION,
        EXPECTED_GENERATION,
        INPUT_JSON,
    )
    return encoded, runtime


class CoreEvidenceBoundsTests(unittest.TestCase):
    def test_exact_core_evidence_bounds_are_accepted(self) -> None:
        exact_ref = "e:" + ("a" * (CORE_MAX_EVIDENCE_REF_LENGTH - 2))
        refs = [exact_ref] * CORE_MAX_EVIDENCE_REFS

        for module, _error_type in CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                encoded, runtime = _invoke(module, refs)
                result = json.loads(encoded)
                self.assertEqual(result["evidence_refs"], refs)
                self.assertEqual(result["usage"]["model_calls"], 0)
                self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)

    def test_more_than_core_max_evidence_refs_fails_closed(self) -> None:
        refs = ["source:fixture"] * (CORE_MAX_EVIDENCE_REFS + 1)

        for module, error_type in CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                runtime = _Runtime(module, refs)
                plugin = module.create_plugin()
                plugin.start(runtime)
                with self.assertRaisesRegex(error_type, "invalid-expert-evidence"):
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

    def test_evidence_ref_longer_than_core_max_fails_closed(self) -> None:
        too_long = "e:" + ("b" * (CORE_MAX_EVIDENCE_REF_LENGTH - 1))
        self.assertEqual(len(too_long), CORE_MAX_EVIDENCE_REF_LENGTH + 1)

        for module, error_type in CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                runtime = _Runtime(module, [too_long])
                plugin = module.create_plugin()
                plugin.start(runtime)
                with self.assertRaisesRegex(error_type, "invalid-expert-evidence"):
                    plugin.invoke(
                        REQUEST_ID,
                        ACTIVATION_ID,
                        EXPERT_OPERATION,
                        EXPECTED_GENERATION,
                        EXPECTED_GENERATION,
                        INPUT_JSON,
                    )
                self.assertEqual(len(runtime.requests), 1)


if __name__ == "__main__":
    unittest.main()
