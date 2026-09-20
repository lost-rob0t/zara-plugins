from __future__ import annotations

import ast
import importlib.util
import json
import pathlib
import sys
import types
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
ACTIVATION_ID = "act:" + "a" * 32
PACKAGES = {
    "javascript": (
        "zara-javascript-expert",
        "zara_javascript_expert",
        "JavaScript",
        "zara:expert/javascript",
        "inspect_module",
        "lost-rob0t/prolog-rlm#500",
        {"source": "export const x = 1", "project_metadata": {}},
    ),
    "typescript": (
        "zara-typescript-expert",
        "zara_typescript_expert",
        "TypeScript",
        "zara:expert/typescript",
        "typecheck",
        "lost-rob0t/prolog-rlm#500",
        {"source": "export const x: number = 1", "project_metadata": {}},
    ),
    "java": (
        "zara-java-expert",
        "zara_java_expert",
        "Java",
        "zara:expert/java",
        "compile_check",
        "lost-rob0t/prolog-rlm#501",
        {"source": "class X {}"},
    ),
    "kotlin": (
        "zara-kotlin-expert",
        "zara_kotlin_expert",
        "Kotlin",
        "zara:expert/kotlin",
        "compile_check",
        "lost-rob0t/prolog-rlm#501",
        {"source": "class X"},
    ),
}


def _install_stubs() -> None:
    tools = types.ModuleType("langchain_core.tools")

    class StructuredTool:
        @classmethod
        def from_function(cls, **kwargs):
            return kwargs

    tools.StructuredTool = StructuredTool
    langchain_core = types.ModuleType("langchain_core")
    langchain_core.tools = tools
    sys.modules.setdefault("langchain_core", langchain_core)
    sys.modules.setdefault("langchain_core.tools", tools)

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
    sys.modules.setdefault("zara", zara)
    sys.modules.setdefault("zara.plugins", plugins)


def _load_plugin(package: str, module_name: str):
    _install_stubs()
    path = ROOT / "plugins" / package / "lib" / module_name / "plugin.py"
    spec = importlib.util.spec_from_file_location(f"test_{module_name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeRuntime:
    def __init__(self, module, *, model_calls: int = 0, stale: bool = False, receipts=None) -> None:
        self.module = module
        self.model_calls = model_calls
        self.stale = stale
        self.receipts = [] if receipts is None else receipts
        self.resolved = []
        self.requests = []

    def resolve_capability(self, capability: str):
        self.resolved.append(capability)
        return object()

    def invoke_capability(self, handle, request):
        del handle
        self.requests.append(request)
        runtime_generation = request["expected_runtime_generation"] - 1 if self.stale else request["expected_runtime_generation"]
        return {
            "protocol": "ZARA-EXPERT/1",
            "request_id": request["request_id"],
            "invocation_id": "inv:fixture",
            "activation_id": request["activation_id"],
            "expert_id": request["expert_id"],
            "expert_version": self.module.PLUGIN_VERSION,
            "manifest_digest": self.module.MANIFEST_DIGEST,
            "expert_operation": request["expert_operation"],
            "resolved_registry_generation": request["expected_registry_generation"],
            "resolved_runtime_generation": runtime_generation,
            "verdict": "succeeded",
            "data": {"verdict": "clean"},
            "evidence_refs": ["fixture:source"],
            "usage": {"model_calls": self.model_calls},
            "effect_receipts": self.receipts,
        }


class ExpertFactory4PackageContractTests(unittest.TestCase):
    def test_packages_are_separate_provider_free_and_syntax_valid(self) -> None:
        forbidden_import_roots = {"openai", "anthropic", "requests", "urllib", "subprocess"}
        for language, (package, module_name, _, expert_id, _, upstream, _) in PACKAGES.items():
            plugin = ROOT / "plugins" / package / "lib" / module_name / "plugin.py"
            source = plugin.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(plugin))
            imported_roots = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_roots.add(node.module.split(".", 1)[0])
            self.assertTrue(forbidden_import_roots.isdisjoint(imported_roots), (language, imported_roots))
            module = _load_plugin(package, module_name)
            self.assertEqual(module.EXPERT_ID, expert_id)
            self.assertEqual(module.UPSTREAM_CONTRACT, upstream)
            self.assertEqual(module.HOST_CAPABILITY, "expert.invoke")

    def test_each_descriptor_is_passive_exact_zero_model(self) -> None:
        for language, (package, module_name, class_name, expert_id, _, _, _) in PACKAGES.items():
            module = _load_plugin(package, module_name)
            runtime = FakeRuntime(module)
            plugin = getattr(module, f"Zara{class_name}ExpertPlugin")()
            plugin.start(runtime)
            descriptor = json.loads(plugin.descriptor())
            self.assertEqual(descriptor["protocol"], "ZARA-EXPERT/1", language)
            self.assertEqual(descriptor["expert_id"], expert_id, language)
            self.assertEqual(descriptor["reasoning_kind"], "symbolic", language)
            self.assertEqual(descriptor["fallback_policy"], "fail_closed", language)
            self.assertEqual(descriptor["delegation_policy"], "never", language)
            self.assertEqual(descriptor["resource_limits"]["max_model_calls"], 0, language)
            self.assertEqual(descriptor["required_capabilities"], ["expert.invoke"], language)
            self.assertEqual(descriptor["possible_effects"], ["none"], language)
            self.assertEqual(runtime.resolved, [], language)
            self.assertEqual(runtime.requests, [], language)

    def test_each_invocation_is_generation_fenced_and_zero_model(self) -> None:
        required = {
            "protocol", "request_id", "operation", "activation_id", "expert_id",
            "expert_operation", "expected_registry_generation", "expected_runtime_generation",
            "input", "limits",
        }
        for language, (package, module_name, class_name, expert_id, operation, _, payload) in PACKAGES.items():
            module = _load_plugin(package, module_name)
            runtime = FakeRuntime(module)
            plugin = getattr(module, f"Zara{class_name}ExpertPlugin")()
            plugin.start(runtime)
            result = json.loads(plugin.invoke("request-1", ACTIVATION_ID, operation, 7, 11, json.dumps(payload)))
            self.assertEqual(runtime.resolved, ["expert.invoke"], language)
            self.assertEqual(set(runtime.requests[0]), required, language)
            self.assertEqual(runtime.requests[0]["expert_id"], expert_id, language)
            self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0, language)
            self.assertEqual(result["usage"]["model_calls"], 0, language)
            self.assertEqual(result["effect_receipts"], [], language)

    def test_model_effect_and_stale_result_fail_closed(self) -> None:
        for language, (package, module_name, class_name, _, operation, _, payload) in PACKAGES.items():
            module = _load_plugin(package, module_name)
            error = getattr(module, f"{class_name}ExpertAdapterError")
            plugin = getattr(module, f"Zara{class_name}ExpertPlugin")()
            encoded = json.dumps(payload)
            plugin.start(FakeRuntime(module, model_calls=1))
            with self.assertRaisesRegex(error, "zero-model-proof-missing", msg=language):
                plugin.invoke("request-1", ACTIVATION_ID, operation, 7, 11, encoded)
            plugin.start(FakeRuntime(module, model_calls=False))
            with self.assertRaisesRegex(error, "zero-model-proof-missing", msg=f"{language}: bool must not equal numeric zero"):
                plugin.invoke("request-1", ACTIVATION_ID, operation, 7, 11, encoded)
            plugin.start(FakeRuntime(module, stale=True))
            with self.assertRaisesRegex(error, "stale-expert-result", msg=language):
                plugin.invoke("request-1", ACTIVATION_ID, operation, 7, 11, encoded)
            plugin.start(FakeRuntime(module, receipts=[{"effect": "filesystem.write"}]))
            with self.assertRaisesRegex(error, "read-only-effect-leak", msg=language):
                plugin.invoke("request-1", ACTIVATION_ID, operation, 7, 11, encoded)

            class MissingReceiptRuntime(FakeRuntime):
                def invoke_capability(self, handle, request):
                    result = super().invoke_capability(handle, request)
                    result.pop("effect_receipts")
                    return result

            plugin.start(MissingReceiptRuntime(module))
            with self.assertRaisesRegex(error, "read-only-effect-proof-missing", msg=f"{language}: missing effect proof"):
                plugin.invoke("request-1", ACTIVATION_ID, operation, 7, 11, encoded)

    def test_language_and_project_boundaries_are_explicit(self) -> None:
        js = (ROOT / "plugins/zara-javascript-expert/README.md").read_text(encoding="utf-8")
        ts = (ROOT / "plugins/zara-typescript-expert/README.md").read_text(encoding="utf-8")
        java = (ROOT / "plugins/zara-java-expert/README.md").read_text(encoding="utf-8")
        kotlin = (ROOT / "plugins/zara-kotlin-expert/README.md").read_text(encoding="utf-8")
        self.assertIn("distinct from TypeScript", js)
        self.assertIn("distinct from JavaScript", ts)
        self.assertIn("observations, never authority", java)
        self.assertIn("observations, never authority", kotlin)


if __name__ == "__main__":
    unittest.main()
