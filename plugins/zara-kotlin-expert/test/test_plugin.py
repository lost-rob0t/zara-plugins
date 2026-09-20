from __future__ import annotations

import json
import unittest

from zara_kotlin_expert.plugin import MANIFEST_DIGEST, KotlinExpertAdapterError, ZaraKotlinExpertPlugin

ACTIVATION = "act:" + "a" * 32

class FakeRuntime:
    def __init__(self, *, model_calls=0, stale=False, receipts=None):
        self.model_calls=model_calls; self.stale=stale; self.receipts=[] if receipts is None else receipts; self.requests=[]; self.resolved=[]
    def resolve_capability(self, capability):
        self.resolved.append(capability); return object()
    def invoke_capability(self, _handle, request):
        self.requests.append(request)
        runtime_generation=request["expected_runtime_generation"] - 1 if self.stale else request["expected_runtime_generation"]
        return {
            "protocol":"ZARA-EXPERT/1", "request_id":request["request_id"], "invocation_id":"inv:fixture",
            "activation_id":request["activation_id"], "expert_id":request["expert_id"], "expert_version":"0.1.0",
            "manifest_digest":MANIFEST_DIGEST, "expert_operation":request["expert_operation"],
            "resolved_registry_generation":request["expected_registry_generation"], "resolved_runtime_generation":runtime_generation,
            "verdict":"succeeded", "data":{"ok":True}, "evidence_refs":["fixture:source"],
            "usage":{"model_calls":self.model_calls}, "effect_receipts":self.receipts,
        }

class ContractTests(unittest.TestCase):
    def plugin(self, runtime=None):
        value=ZaraKotlinExpertPlugin(); value.start(runtime or FakeRuntime()); return value
    def test_descriptor_matches_current_closed_contract_and_zero_model(self):
        d=json.loads(self.plugin().descriptor())
        self.assertEqual(d["expert_id"], 'zara:expert/kotlin')
        self.assertEqual(d["reasoning_kind"], "symbolic")
        self.assertEqual(d["possible_effects"], ["none"])
        self.assertEqual(d["fallback_policy"], "fail_closed")
        self.assertEqual(d["delegation_policy"], "never")
        self.assertEqual(d["resource_limits"]["max_model_calls"], 0)
        self.assertIn("applicability", d); self.assertNotIn("required_observations", d); self.assertNotIn("placement", d)
        for op in d["operations"]:
            self.assertEqual(set(op), {"operation_id","input_schema","output_schema"})
    def test_language_boundary_is_explicit(self):
        ops={item["operation_id"] for item in json.loads(self.plugin().descriptor())["operations"]}
        self.assertIn("inspect_jvm_project", ops); self.assertIn("compile_check", ops); self.assertIn("inspect_coroutines", ops)
        compile_op=next(item for item in json.loads(self.plugin().descriptor())["operations"] if item["operation_id"]=="compile_check")
        names={field["name"] for field in compile_op["input_schema"]["fields"]}
        self.assertTrue({"jvm_project_metadata","gradle_project_metadata","android_project_metadata"} <= names)
    def test_canonical_invoke_and_exact_zero_model(self):
        runtime=FakeRuntime(); p=self.plugin(runtime)
        result=json.loads(p.invoke("req:1", ACTIVATION, 'compile_check', 0, 0, "{\"source\": \"class X {}\"}"))
        self.assertEqual(runtime.resolved, ["expert.invoke"])
        self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)
        self.assertEqual(result["usage"]["model_calls"], 0)
        self.assertEqual(result["effect_receipts"], [])
    def test_activation_and_generation_fences(self):
        p=self.plugin()
        with self.assertRaisesRegex(KotlinExpertAdapterError, "invalid-activation-id"):
            p.invoke("req:1", "activation-1", 'compile_check', 0, 0, "{\"source\": \"class X {}\"}")
        with self.assertRaisesRegex(KotlinExpertAdapterError, "invalid-registry-generation"):
            p.invoke("req:1", ACTIVATION, 'compile_check', False, 0, "{\"source\": \"class X {}\"}")
    def test_stale_result_rejected(self):
        with self.assertRaisesRegex(KotlinExpertAdapterError, "stale-expert-result"):
            self.plugin(FakeRuntime(stale=True)).invoke("req:1", ACTIVATION, 'compile_check', 1, 1, "{\"source\": \"class X {}\"}")
    def test_nonzero_or_boolean_model_usage_rejected(self):
        for value in (1, False):
            with self.subTest(value=value), self.assertRaisesRegex(KotlinExpertAdapterError, "zero-model-proof-missing"):
                self.plugin(FakeRuntime(model_calls=value)).invoke("req:1", ACTIVATION, 'compile_check', 1, 1, "{\"source\": \"class X {}\"}")
    def test_read_only_effect_proof_required_and_empty(self):
        with self.assertRaisesRegex(KotlinExpertAdapterError, "read-only-effect-leak"):
            self.plugin(FakeRuntime(receipts=[{"effect":"filesystem.write"}])).invoke("req:1", ACTIVATION, 'compile_check', 1, 1, "{\"source\": \"class X {}\"}")
        class Missing(FakeRuntime):
            def invoke_capability(self, handle, request):
                out=super().invoke_capability(handle, request); out.pop("effect_receipts"); return out
        with self.assertRaisesRegex(KotlinExpertAdapterError, "read-only-effect-proof-missing"):
            self.plugin(Missing()).invoke("req:1", ACTIVATION, 'compile_check', 1, 1, "{\"source\": \"class X {}\"}")
    def test_unknown_or_malformed_input_fails_before_host(self):
        runtime=FakeRuntime(); p=self.plugin(runtime)
        with self.assertRaises(KotlinExpertAdapterError):
            p.invoke("req:1", ACTIVATION, 'compile_check', 1, 1, '{"unknown":1}')
        self.assertEqual(runtime.requests, [])

if __name__ == "__main__": unittest.main()
