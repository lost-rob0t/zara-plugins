from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOST_LIB = ROOT / "plugins" / "zara-expert" / "lib"
if str(HOST_LIB) not in sys.path:
    sys.path.insert(0, str(HOST_LIB))

ACTIVATION_ID = "act:" + "a" * 32
INVOCATION_ID = "inv:" + "b" * 32
REQUEST_ID = "req:result-wire-containers"

CASES = {
    "javascript": (
        "zara-javascript-expert",
        "zara_javascript_expert",
        "JavaScriptExpertAdapterError",
        {"source": "const x = 1;", "source_generation": "project:7"},
    ),
    "typescript": (
        "zara-typescript-expert",
        "zara_typescript_expert",
        "TypeScriptExpertAdapterError",
        {"source": "const x: number = 1;", "source_generation": "project:7"},
    ),
    "java": (
        "zara-java-expert",
        "zara_java_expert",
        "JavaExpertAdapterError",
        {"source": "class A {}", "source_generation": "project:7"},
    ),
    "kotlin": (
        "zara-kotlin-expert",
        "zara_kotlin_expert",
        "KotlinExpertAdapterError",
        {"source": "fun main() = Unit", "source_generation": "project:7"},
    ),
}


class HostData(dict):
    """Non-canonical host-owned mapping that json.dumps would normalize."""


def _install_dependency_stubs() -> None:
    langchain_core = types.ModuleType("langchain_core")
    langchain_tools = types.ModuleType("langchain_core.tools")

    class StructuredTool:
        pass

    langchain_tools.StructuredTool = StructuredTool
    langchain_core.tools = langchain_tools
    sys.modules["langchain_core"] = langchain_core
    sys.modules["langchain_core.tools"] = langchain_tools

    plugins = types.ModuleType("zara.plugins")

    class PluginMetadata:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class ServicePlugin:
        pass

    plugins.PluginMetadata = PluginMetadata
    plugins.ServicePlugin = ServicePlugin
    zara = types.ModuleType("zara")
    zara.plugins = plugins
    sys.modules["zara"] = zara
    sys.modules["zara.plugins"] = plugins


def _load_plugin(package: str, module_name: str, suffix: str):
    _install_dependency_stubs()
    path = ROOT / "plugins" / package / "lib" / module_name / "plugin.py"
    spec = importlib.util.spec_from_file_location(
        f"test_four_language_result_wire_{module_name}_{suffix}",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ResultWireRuntime:
    def __init__(self, module, *, data, evidence_refs):
        self.module = module
        self.data = data
        self.evidence_refs = evidence_refs
        self.requests: list[dict[str, object]] = []

    def resolve_capability(self, capability):
        if capability != "expert.invoke":
            raise AssertionError(capability)
        return object()

    def invoke_capability(self, _handle, request):
        self.requests.append(request)
        return {
            "protocol": self.module.PROTOCOL,
            "request_id": request["request_id"],
            "invocation_id": INVOCATION_ID,
            "activation_id": request["activation_id"],
            "expert_id": request["expert_id"],
            "expert_version": self.module.PLUGIN_VERSION,
            "manifest_digest": self.module.MANIFEST_DIGEST,
            "expert_operation": request["expert_operation"],
            "resolved_registry_generation": request["expected_registry_generation"],
            "resolved_runtime_generation": request["expected_runtime_generation"],
            "verdict": "failed",
            "data": self.data,
            "evidence_refs": self.evidence_refs,
            "usage": {"model_calls": 0},
            "effect_receipts": [],
            "error_code": "unavailable",
            "error_message": "fixture failure",
        }


class FourLanguageResultWireContainerTests(unittest.TestCase):
    def _invoke_and_require_error(
        self,
        *,
        language: str,
        package: str,
        module_name: str,
        error_class_name: str,
        payload: dict[str, object],
        data,
        evidence_refs,
        expected_error: str,
    ) -> None:
        module = _load_plugin(package, module_name, language)
        plugin = module.create_plugin()
        runtime = ResultWireRuntime(
            module,
            data=data,
            evidence_refs=evidence_refs,
        )
        plugin.start(runtime)
        error_class = getattr(module, error_class_name)
        with self.assertRaisesRegex(error_class, expected_error):
            plugin.invoke(
                request_id=REQUEST_ID,
                activation_id=ACTIVATION_ID,
                expert_operation="inspect",
                expected_registry_generation=1,
                expected_runtime_generation=1,
                input_json=module._json(payload),
            )
        self.assertEqual(len(runtime.requests), 1)
        self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)

    def test_host_data_must_be_exact_json_object(self) -> None:
        for language, (package, module_name, error_class_name, payload) in CASES.items():
            with self.subTest(language=language):
                self._invoke_and_require_error(
                    language=language,
                    package=package,
                    module_name=module_name,
                    error_class_name=error_class_name,
                    payload=payload,
                    data=HostData(),
                    evidence_refs=[],
                    expected_error="invalid-expert-data",
                )

    def test_host_evidence_refs_must_be_exact_json_array(self) -> None:
        for language, (package, module_name, error_class_name, payload) in CASES.items():
            with self.subTest(language=language):
                self._invoke_and_require_error(
                    language=language,
                    package=package,
                    module_name=module_name,
                    error_class_name=error_class_name,
                    payload=payload,
                    data={},
                    evidence_refs=(),
                    expected_error="invalid-expert-evidence",
                )


if __name__ == "__main__":
    unittest.main()
