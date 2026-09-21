from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_typescript_expert.plugin import LANGUAGE_BOUNDARIES, MANIFEST_DIGEST, TypeScriptExpertAdapterError, ZaraTypeScriptExpertPlugin

ACTIVATION = "act:" + "a" * 32
CANONICAL_OPERATIONS = {"match", "inspect", "diagnose", "repair.preview", "repair.verify", "style.rules", "explain"}


class FakeRuntime:
    def __init__(self, *, model_calls=0, stale=False, receipts=None):
        self.model_calls=model_calls; self.stale=stale; self.receipts=[] if receipts is None else receipts; self.requests=[]; self.resolved=[]
    def resolve_capability(self, capability):
        self.resolved.append(capability); return object()
    def invoke_capability(self, _handle, request):
        self.requests.append(request)
        runtime_generation=request["expected_runtime_generation"] - 1 if self.stale else request["expected_runtime_generation"]
        return {"protocol":"ZARA-EXPERT/1","request_id":request["request_id"],"activation_id":request["activation_id"],"expert_id":request["expert_id"],"expert_version":"0.1.0","manifest_digest":MANIFEST_DIGEST,"expert_operation":request["expert_operation"],"resolved_registry_generation":request["expected_registry_generation"],"resolved_runtime_generation":runtime_generation,"verdict":"succeeded","data":{"result":{}},"evidence_refs":[],"usage":{"model_calls":self.model_calls},"effect_receipts":self.receipts}


class ContractTests(unittest.TestCase):
    def plugin(self, runtime=None):
        value=ZaraTypeScriptExpertPlugin(); value.start(runtime or FakeRuntime()); return value

    def test_descriptor_uses_canonical_zero_model_language_abi(self):
        descriptor=json.loads(self.plugin().descriptor())
        self.assertEqual({item["operation_id"] for item in descriptor["operations"]}, CANONICAL_OPERATIONS)
        self.assertEqual(descriptor["resource_limits"]["max_model_calls"], 0)
        self.assertEqual(descriptor["fallback_policy"], "fail_closed")

    def test_typescript_boundary_is_not_javascript(self):
        self.assertEqual(LANGUAGE_BOUNDARIES["extensions"], (".ts", ".tsx", ".mts", ".cts"))
        self.assertIn("types", LANGUAGE_BOUNDARIES["evidence_topics"])
        self.assertIn("tsx", LANGUAGE_BOUNDARIES["evidence_topics"])
        self.assertNotIn("jsx", LANGUAGE_BOUNDARIES["evidence_topics"])

    def test_inspect_and_fences(self):
        payload=json.dumps({"source":"export const x: number = 1","source_generation":"buffer:1"})
        runtime=FakeRuntime(); result=json.loads(self.plugin(runtime).invoke("req:1",ACTIVATION,"inspect",1,2,payload))
        self.assertEqual(runtime.resolved,["expert.invoke"]); self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"],0); self.assertEqual(result["usage"]["model_calls"],0)
        with self.assertRaisesRegex(TypeScriptExpertAdapterError,"stale-expert-result"): self.plugin(FakeRuntime(stale=True)).invoke("req:1",ACTIVATION,"inspect",1,2,payload)
        with self.assertRaisesRegex(TypeScriptExpertAdapterError,"zero-model-proof-missing"): self.plugin(FakeRuntime(model_calls=1)).invoke("req:1",ACTIVATION,"inspect",1,2,payload)
        with self.assertRaisesRegex(TypeScriptExpertAdapterError,"read-only-effect-leak"): self.plugin(FakeRuntime(receipts=[{"effect":"write"}])).invoke("req:1",ACTIVATION,"inspect",1,2,payload)
        with self.assertRaisesRegex(TypeScriptExpertAdapterError,"unsupported-expert-operation"): self.plugin().invoke("req:1",ACTIVATION,"typecheck",1,2,payload)


if __name__ == "__main__": unittest.main()
