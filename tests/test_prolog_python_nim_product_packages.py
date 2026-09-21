from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
ACTIVATION_ID = "act:" + "a" * 32
OPERATIONS = {"match", "inspect", "diagnose", "repair.preview", "repair.verify", "style.rules", "explain"}
CASES = {
    "prolog": ("zara-prolog-expert", "zara_prolog_expert", "Prolog", "zara:expert/prolog", "lost-rob0t/prolog-rlm#495", 495, ".zara/experts/prolog", {"source": "p(x).", "source_generation": "buffer:pl:1"}),
    "python": ("zara-python-expert", "zara_python_expert", "Python", "zara:expert/python", "lost-rob0t/prolog-rlm#498", 498, ".zara/experts/python", {"source": "x = 1", "source_generation": "buffer:py:1"}),
    "nim": ("zara-nim-expert", "zara_nim_expert", "Nim", "zara:expert/nim", "lost-rob0t/prolog-rlm#499", 499, ".zara/experts/nim", {"source": "let x = 1", "source_generation": "buffer:nim:1"}),
}


def _install_stubs() -> None:
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


def _load(package: str, module_name: str):
    _install_stubs()
    path = ROOT / "plugins" / package / "lib" / module_name / "plugin.py"
    spec = importlib.util.spec_from_file_location(f"test_{module_name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeRuntime:
    def __init__(self, module, *, model_calls=0, receipts=None, stale=False, usage_extra=False):
        self.module = module
        self.model_calls = model_calls
        self.receipts = [] if receipts is None else receipts
        self.stale = stale
        self.usage_extra = usage_extra
        self.requests: list[dict[str, object]] = []
        self.resolved: list[str] = []

    def resolve_capability(self, capability):
        self.resolved.append(capability)
        return object()

    def invoke_capability(self, _handle, request):
        self.requests.append(request)
        op = request["expert_operation"]
        data = {
            "match": {"applicable": True},
            "inspect": {"result": {"language": self.module.LANGUAGE_BOUNDARIES["language"]}},
            "diagnose": {"diagnostics": []},
            "repair.preview": {"repair": {"kind": "preview"}},
            "repair.verify": {"verified": True, "postcondition_evidence": {"fresh": True}},
            "style.rules": {"style_rules": ["fixture-rule"], "style_provenance": ["fixture:project-style"]},
            "explain": {"explanation": {"because": "fixture-evidence"}},
        }[op]
        usage = {"model_calls": self.model_calls}
        if self.usage_extra:
            usage["provider_calls"] = 0
        return {
            "protocol": self.module.PROTOCOL,
            "request_id": request["request_id"],
            "activation_id": request["activation_id"],
            "expert_id": request["expert_id"],
            "expert_version": self.module.PLUGIN_VERSION,
            "manifest_digest": self.module.MANIFEST_DIGEST,
            "expert_operation": op,
            "resolved_registry_generation": request["expected_registry_generation"],
            "resolved_runtime_generation": request["expected_runtime_generation"] - (1 if self.stale else 0),
            "verdict": "succeeded",
            "data": data,
            "evidence_refs": ["fixture:evidence"],
            "usage": usage,
            "effect_receipts": self.receipts,
        }


class PrologPythonNimProductPackageTests(unittest.TestCase):
    def test_packages_are_provider_free_canonical_leaf_adapters(self):
        forbidden = {"openai", "anthropic", "requests", "urllib", "subprocess", "socket"}
        for language, (package, module_name, class_name, expert_id, upstream, _, _, _) in CASES.items():
            path = ROOT / "plugins" / package / "lib" / module_name / "plugin.py"
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            roots = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots.update(alias.name.split(".", 1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    roots.add(node.module.split(".", 1)[0])
            self.assertTrue(forbidden.isdisjoint(roots), (language, roots))
            module = _load(package, module_name)
            plugin = getattr(module, f"Zara{class_name}ExpertPlugin")()
            descriptor = json.loads(plugin.descriptor())
            self.assertEqual(module.EXPERT_ID, expert_id)
            self.assertEqual(module.UPSTREAM_CONTRACT, upstream)
            self.assertEqual(module.HOST_CAPABILITY, "expert.invoke")
            self.assertEqual(set(module.OPERATION_FIELDS), OPERATIONS)
            self.assertEqual({item["operation_id"] for item in descriptor["operations"]}, OPERATIONS)
            self.assertEqual(descriptor["reasoning_kind"], "symbolic")
            self.assertEqual(descriptor["fallback_policy"], "fail_closed")
            self.assertEqual(descriptor["resource_limits"]["max_model_calls"], 0)
            self.assertIn("style.rules", {item["operation_id"] for item in descriptor["operations"]})
            self.assertEqual(plugin.tools(), ())

    def test_canonical_host_preserves_zero_model_generation_and_effect_fences(self):
        for language, (package, module_name, class_name, _, _, _, _, inspect_payload) in CASES.items():
            module = _load(package, module_name)
            plugin_class = getattr(module, f"Zara{class_name}ExpertPlugin")
            error_class = getattr(module, f"{class_name}ExpertAdapterError")
            runtime = FakeRuntime(module)
            plugin = plugin_class()
            plugin.start(runtime)
            result = json.loads(plugin.invoke("request-1", ACTIVATION_ID, "inspect", 7, 11, json.dumps(inspect_payload)))
            self.assertEqual(runtime.resolved, ["expert.invoke"], language)
            self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0, language)
            self.assertEqual(result["usage"], {"model_calls": 0}, language)
            self.assertEqual(result["effect_receipts"], [], language)

            for op, payload in (
                ("style.rules", {"source": inspect_payload["source"], "project_style": "project:fixture"}),
                ("explain", {"decision_ref": "decision:fixture", "source_generation": inspect_payload["source_generation"]}),
            ):
                rendered = json.loads(plugin.invoke(f"request-{op}", ACTIVATION_ID, op, 7, 11, json.dumps(payload)))
                self.assertEqual(rendered["usage"]["model_calls"], 0, (language, op))
                self.assertTrue(rendered["evidence_refs"], (language, op))

            for broken_runtime, message in (
                (FakeRuntime(module, model_calls=1), "zero-model-proof-missing"),
                (FakeRuntime(module, usage_extra=True), "zero-model-proof-missing"),
                (FakeRuntime(module, stale=True), "stale-expert-result"),
                (FakeRuntime(module, receipts=[{"effect": "write"}]), "read-only-effect-leak"),
            ):
                broken = plugin_class()
                broken.start(broken_runtime)
                with self.assertRaisesRegex(error_class, message, msg=language):
                    broken.invoke("request-bad", ACTIVATION_ID, "inspect", 7, 11, json.dumps(inspect_payload))

    def test_source_locks_bind_canonical_dotfiles_and_prolog_rlm_contracts(self):
        for language, (package, _, _, expert_id, _, runtime_issue, source_path, _) in CASES.items():
            lock = json.loads((ROOT / "plugins" / package / "expert-source.lock.json").read_text(encoding="utf-8"))
            self.assertEqual(lock["expert_id"], expert_id, language)
            self.assertEqual(lock["canonical_source"]["repository"], "lost-rob0t/dotfiles", language)
            self.assertEqual(lock["canonical_source"]["path"], source_path, language)
            self.assertEqual(lock["canonical_source"]["commit"], "5b01f03bdce98bc55f9f3cc76a1023b91ab63784", language)
            self.assertEqual(lock["runtime_contract"]["issue"], runtime_issue, language)

    def test_registry_discovers_all_three_packages(self):
        registry = json.loads((ROOT / "plugins.json").read_text(encoding="utf-8"))
        entries = {entry["name"]: entry for entry in registry["plugins"]}
        for _, (package, module_name, _, _, _, _, _, _) in CASES.items():
            self.assertIn(package, entries)
            entry = entries[package]
            self.assertEqual(entry["entrypoint"], f"zara-plugin/{module_name}_entrypoint.py")
            self.assertEqual(entry["nix"]["package"], package)


if __name__ == "__main__":
    unittest.main()
