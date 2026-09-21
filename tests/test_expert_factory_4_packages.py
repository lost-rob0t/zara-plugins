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
CANONICAL_OPERATIONS = {"match", "inspect", "diagnose", "repair.preview", "repair.verify", "style.rules", "explain"}
PACKAGES = {
    "javascript": ("zara-javascript-expert", "zara_javascript_expert", "JavaScript", "zara:expert/javascript", "lost-rob0t/prolog-rlm#500", {"source": "export const x = 1", "source_generation": "buffer:js:1"}),
    "typescript": ("zara-typescript-expert", "zara_typescript_expert", "TypeScript", "zara:expert/typescript", "lost-rob0t/prolog-rlm#500", {"source": "export const x: number = 1", "source_generation": "buffer:ts:1"}),
    "java": ("zara-java-expert", "zara_java_expert", "Java", "zara:expert/java", "lost-rob0t/prolog-rlm#501", {"source": "class X {}", "source_generation": "buffer:java:1"}),
    "kotlin": ("zara-kotlin-expert", "zara_kotlin_expert", "Kotlin", "zara:expert/kotlin", "lost-rob0t/prolog-rlm#501", {"source": "class X", "source_generation": "buffer:kotlin:1"}),
}


def _install_stubs() -> None:
    plugins = types.ModuleType("zara.plugins")
    class PluginMetadata:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    class ServicePlugin: pass
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
    def __init__(self, module, *, model_calls=0, stale=False, receipts=None):
        self.module=module; self.model_calls=model_calls; self.stale=stale; self.receipts=[] if receipts is None else receipts; self.resolved=[]; self.requests=[]
    def resolve_capability(self, capability): self.resolved.append(capability); return object()
    def invoke_capability(self, _handle, request):
        self.requests.append(request)
        runtime_generation=request["expected_runtime_generation"] - 1 if self.stale else request["expected_runtime_generation"]
        return {"protocol":"ZARA-EXPERT/1","request_id":request["request_id"],"activation_id":request["activation_id"],"expert_id":request["expert_id"],"expert_version":self.module.PLUGIN_VERSION,"manifest_digest":self.module.MANIFEST_DIGEST,"expert_operation":request["expert_operation"],"resolved_registry_generation":request["expected_registry_generation"],"resolved_runtime_generation":runtime_generation,"verdict":"succeeded","data":{"result":{}},"evidence_refs":["fixture:source"],"usage":{"model_calls":self.model_calls},"effect_receipts":self.receipts}


class ExpertFactory4PackageContractTests(unittest.TestCase):
    def test_packages_are_separate_provider_free_and_use_canonical_operations(self):
        forbidden_import_roots={"openai","anthropic","requests","urllib","subprocess"}
        for language,(package,module_name,_,expert_id,upstream,_) in PACKAGES.items():
            path=ROOT / "plugins" / package / "lib" / module_name / "plugin.py"
            tree=ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            roots=set()
            for node in ast.walk(tree):
                if isinstance(node,ast.Import): roots.update(alias.name.split(".",1)[0] for alias in node.names)
                elif isinstance(node,ast.ImportFrom) and node.module: roots.add(node.module.split(".",1)[0])
            self.assertTrue(forbidden_import_roots.isdisjoint(roots), (language, roots))
            module=_load_plugin(package,module_name)
            self.assertEqual(module.EXPERT_ID,expert_id); self.assertEqual(module.UPSTREAM_CONTRACT,upstream); self.assertEqual(module.HOST_CAPABILITY,"expert.invoke")
            self.assertEqual(set(module.OPERATION_FIELDS), CANONICAL_OPERATIONS)

    def test_descriptors_are_passive_and_exact_zero_model(self):
        for language,(package,module_name,class_name,expert_id,_,_) in PACKAGES.items():
            module=_load_plugin(package,module_name); runtime=FakeRuntime(module); plugin=getattr(module,f"Zara{class_name}ExpertPlugin")(); plugin.start(runtime); descriptor=json.loads(plugin.descriptor())
            self.assertEqual(descriptor["expert_id"],expert_id,language); self.assertEqual(descriptor["reasoning_kind"],"symbolic",language); self.assertEqual(descriptor["fallback_policy"],"fail_closed",language); self.assertEqual(descriptor["resource_limits"]["max_model_calls"],0,language); self.assertEqual(runtime.requests,[],language)

    def test_canonical_invoke_generation_model_and_effect_fences(self):
        for language,(package,module_name,class_name,_,_,payload) in PACKAGES.items():
            module=_load_plugin(package,module_name); error=getattr(module,f"{class_name}ExpertAdapterError"); encoded=json.dumps(payload)
            runtime=FakeRuntime(module); plugin=getattr(module,f"Zara{class_name}ExpertPlugin")(); plugin.start(runtime); result=json.loads(plugin.invoke("request-1",ACTIVATION_ID,"inspect",7,11,encoded))
            self.assertEqual(runtime.resolved,["expert.invoke"],language); self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"],0,language); self.assertEqual(result["usage"]["model_calls"],0,language); self.assertEqual(result["effect_receipts"],[],language)
            plugin.start(FakeRuntime(module,model_calls=1));
            with self.assertRaisesRegex(error,"zero-model-proof-missing",msg=language): plugin.invoke("request-1",ACTIVATION_ID,"inspect",7,11,encoded)
            plugin.start(FakeRuntime(module,stale=True));
            with self.assertRaisesRegex(error,"stale-expert-result",msg=language): plugin.invoke("request-1",ACTIVATION_ID,"inspect",7,11,encoded)
            plugin.start(FakeRuntime(module,receipts=[{"effect":"write"}]));
            with self.assertRaisesRegex(error,"read-only-effect-leak",msg=language): plugin.invoke("request-1",ACTIVATION_ID,"inspect",7,11,encoded)

    def test_language_and_project_boundaries_are_explicit(self):
        js=_load_plugin("zara-javascript-expert","zara_javascript_expert").LANGUAGE_BOUNDARIES
        ts=_load_plugin("zara-typescript-expert","zara_typescript_expert").LANGUAGE_BOUNDARIES
        java=_load_plugin("zara-java-expert","zara_java_expert").LANGUAGE_BOUNDARIES
        kotlin=_load_plugin("zara-kotlin-expert","zara_kotlin_expert").LANGUAGE_BOUNDARIES
        self.assertTrue(set(js["extensions"]).isdisjoint(ts["extensions"]))
        self.assertTrue(set(java["extensions"]).isdisjoint(kotlin["extensions"]))
        self.assertNotIn("types",js["evidence_topics"]); self.assertIn("types",ts["evidence_topics"])
        self.assertNotIn("coroutines",java["evidence_topics"]); self.assertIn("coroutines",kotlin["evidence_topics"])
        for boundary in (java,kotlin):
            self.assertEqual(boundary["project_metadata_policy"],"observation_only")
            self.assertTrue(boundary["jvm_project_metadata"] and boundary["gradle_project_metadata"] and boundary["android_project_metadata"])


if __name__ == "__main__": unittest.main()
