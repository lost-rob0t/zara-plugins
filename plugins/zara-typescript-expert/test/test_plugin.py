from __future__ import annotations

import json
import unittest

from zara_typescript_expert.plugin import TypeScriptExpertAdapterError, ZaraTypeScriptExpertPlugin


class FakeRuntime:
    node_id = "node.local"
    runtime_id = "zara-runtime"
    registry_generation = 7

    def __init__(self, *, model_calls: object = 0, stale: bool = False, receipts=None) -> None:
        self.model_calls = model_calls
        self.stale = stale
        self.receipts = [] if receipts is None else receipts
        self.resolved = []
        self.requests = []

    def resolve_capability(self, capability: str):
        self.resolved.append(capability)
        return object()

    def invoke_capability(self, handle, request):
        self.requests.append(request)
        generation = request["expected_runtime_generation"] - 1 if self.stale else request["expected_runtime_generation"]
        return {
            "request_id": request["request_id"],
            "registry_generation": request["expected_registry_generation"],
            "runtime_generation": generation,
            "status": "succeeded",
            "data": {"verdict": "clean"},
            "evidence": [{"kind": "source", "ref": "fixture"}],
            "explanation": [{"kind": "rule", "id": "fixture-rule"}],
            "usage": {"model_calls": self.model_calls},
            "side_effect_receipts": self.receipts,
        }


class TypeScriptExpertPluginTests(unittest.TestCase):
    operation = "typecheck"

    def _plugin(self, runtime=None):
        plugin = ZaraTypeScriptExpertPlugin()
        plugin.start(FakeRuntime() if runtime is None else runtime)
        return plugin

    def test_descriptor_is_passive_pure_symbolic(self) -> None:
        runtime = FakeRuntime()
        plugin = self._plugin(runtime)
        descriptor = json.loads(plugin.descriptor())
        self.assertEqual(descriptor["protocol"], "ZARA-EXPERT/1")
        self.assertEqual(descriptor["expert_id"], "language:typescript")
        self.assertEqual(descriptor["reasoning_kind"], "symbolic")
        self.assertEqual(descriptor["fallback_policy"], "none")
        self.assertEqual(descriptor["resource_limits"]["max_model_calls"], 0)
        self.assertEqual(descriptor["required_capabilities"], ["expert.invoke"])
        self.assertEqual(descriptor["possible_effects"], [])
        self.assertEqual(runtime.resolved, [])
        self.assertEqual(runtime.requests, [])

    def test_invocation_is_generation_fenced_exact_zero_model(self) -> None:
        runtime = FakeRuntime()
        plugin = self._plugin(runtime)
        result = json.loads(plugin.invoke("request-1", "activation-1", self.operation, 7, 11, '{"subject_id":"fixture"}'))
        self.assertEqual(runtime.resolved, ["expert.invoke"])
        self.assertEqual(runtime.requests[0]["expert_id"], "language:typescript")
        self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)
        self.assertEqual(result["usage"]["model_calls"], 0)
        self.assertEqual(result["side_effect_receipts"], [])

    def test_unknown_effectful_operation_rejected_before_host(self) -> None:
        runtime = FakeRuntime()
        plugin = self._plugin(runtime)
        with self.assertRaisesRegex(TypeScriptExpertAdapterError, "unsupported-expert-operation"):
            plugin.invoke("request-1", "activation-1", "repair_apply", 7, 11, "{}")
        self.assertEqual(runtime.requests, [])

    def test_nonzero_or_boolean_model_usage_fails_closed(self) -> None:
        for model_calls in (1, False):
            with self.subTest(model_calls=model_calls):
                plugin = self._plugin(FakeRuntime(model_calls=model_calls))
                with self.assertRaisesRegex(TypeScriptExpertAdapterError, "zero-model-proof-missing"):
                    plugin.invoke("request-1", "activation-1", self.operation, 7, 11, "{}")

    def test_stale_generation_is_rejected(self) -> None:
        plugin = self._plugin(FakeRuntime(stale=True))
        with self.assertRaisesRegex(TypeScriptExpertAdapterError, "stale-or-unbound-expert-result"):
            plugin.invoke("request-1", "activation-1", self.operation, 7, 11, "{}")

    def test_effect_receipt_is_rejected(self) -> None:
        plugin = self._plugin(FakeRuntime(receipts=[{"effect": "filesystem.write"}]))
        with self.assertRaisesRegex(TypeScriptExpertAdapterError, "unexpected-side-effect-receipt"):
            plugin.invoke("request-1", "activation-1", self.operation, 7, 11, "{}")

    def test_missing_effect_receipt_proof_is_rejected(self) -> None:
        class MissingReceiptRuntime(FakeRuntime):
            def invoke_capability(self, handle, request):
                result = super().invoke_capability(handle, request)
                result.pop("side_effect_receipts")
                return result

        plugin = self._plugin(MissingReceiptRuntime())
        with self.assertRaisesRegex(TypeScriptExpertAdapterError, "unexpected-side-effect-receipt"):
            plugin.invoke("request-1", "activation-1", self.operation, 7, 11, "{}")

    def test_malformed_input_fails_before_host(self) -> None:
        runtime = FakeRuntime()
        plugin = self._plugin(runtime)
        with self.assertRaisesRegex(TypeScriptExpertAdapterError, "input-must-be-object"):
            plugin.invoke("request-1", "activation-1", self.operation, 7, 11, "[]")
        self.assertEqual(runtime.requests, [])


if __name__ == "__main__":
    unittest.main()
