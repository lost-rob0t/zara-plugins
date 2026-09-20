from __future__ import annotations

import json
import unittest

from zara_bash_expert.plugin import BashExpertAdapterError, ZaraBashExpertPlugin


class FakeRuntime:
    def __init__(self, *, model_calls: int = 0, side_effect_receipts=None) -> None:
        self.model_calls = model_calls
        self.side_effect_receipts = [] if side_effect_receipts is None else side_effect_receipts
        self.resolved = []
        self.requests = []

    def resolve_capability(self, capability: str):
        self.resolved.append(capability)
        return object()

    def invoke_capability(self, handle, request):
        self.requests.append(request)
        return {
            "status": "succeeded",
            "data": {"verdict": "clean"},
            "evidence": [{"kind": "source", "ref": ".bashrc"}],
            "usage": {"model_calls": self.model_calls},
            "side_effect_receipts": self.side_effect_receipts,
        }


class BashExpertPluginTests(unittest.TestCase):
    def test_start_and_descriptor_do_not_source_or_execute_shell(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraBashExpertPlugin()
        plugin.start(runtime)

        descriptor = json.loads(plugin.descriptor())

        self.assertEqual(descriptor["protocol"], "ZARA-EXPERT/1")
        self.assertEqual(descriptor["reasoning_kind"], "symbolic")
        self.assertEqual(descriptor["resource_limits"]["max_model_calls"], 0)
        self.assertEqual(descriptor["fallback_policy"], "fail-closed-no-model")
        self.assertEqual(runtime.resolved, [])
        self.assertEqual(runtime.requests, [])

    def test_read_only_invocation_uses_canonical_capability_and_zero_model_limit(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraBashExpertPlugin()
        plugin.start(runtime)

        result = json.loads(
            plugin.invoke("activation-2", "inspect_source_graph", '{"path":".bashrc"}')
        )

        self.assertEqual(runtime.resolved, ["expert.invoke"])
        self.assertEqual(len(runtime.requests), 1)
        request = runtime.requests[0]
        self.assertEqual(request["protocol"], "ZARA-EXPERT/1")
        self.assertEqual(request["expert_id"], "zara:expert/bash")
        self.assertEqual(request["expert_operation"], "inspect_source_graph")
        self.assertEqual(request["limits"]["max_model_calls"], 0)
        self.assertEqual(request["effect_policy"], "deny")
        self.assertEqual(result["usage"]["model_calls"], 0)
        self.assertEqual(result["side_effect_receipts"], [])

    def test_effectful_or_unknown_operation_is_rejected_before_host(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraBashExpertPlugin()
        plugin.start(runtime)

        with self.assertRaisesRegex(BashExpertAdapterError, "unsupported-expert-operation"):
            plugin.invoke("activation-2", "execute", '{"argv":["rm","-rf","/"]}')

        self.assertEqual(runtime.resolved, [])
        self.assertEqual(runtime.requests, [])

    def test_missing_composition_fails_closed_without_shell_or_model_fallback(self) -> None:
        plugin = ZaraBashExpertPlugin()
        plugin.start(object())

        with self.assertRaisesRegex(BashExpertAdapterError, "expert-host-composition-unavailable"):
            plugin.invoke("activation-2", "parse", '{"source":"echo ok"}')

    def test_nonzero_or_missing_model_usage_is_rejected(self) -> None:
        plugin = ZaraBashExpertPlugin()
        plugin.start(FakeRuntime(model_calls=1))
        with self.assertRaisesRegex(BashExpertAdapterError, "zero-model-proof-missing"):
            plugin.invoke("activation-2", "parse", '{"source":"echo ok"}')

        class MissingUsageRuntime(FakeRuntime):
            def invoke_capability(self, handle, request):
                self.requests.append(request)
                return {
                    "status": "succeeded",
                    "data": {},
                    "side_effect_receipts": [],
                }

        plugin.start(MissingUsageRuntime())
        with self.assertRaisesRegex(BashExpertAdapterError, "zero-model-proof-missing"):
            plugin.invoke("activation-2", "parse", '{"source":"echo ok"}')

    def test_read_only_result_with_effect_receipt_is_rejected(self) -> None:
        plugin = ZaraBashExpertPlugin()
        plugin.start(FakeRuntime(side_effect_receipts=[{"effect": "bash.execute"}]))

        with self.assertRaisesRegex(BashExpertAdapterError, "read-only-effect-leak"):
            plugin.invoke("activation-2", "parse", '{"source":"echo ok"}')

    def test_invalid_or_deep_input_never_reaches_host(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraBashExpertPlugin()
        plugin.start(runtime)

        with self.assertRaisesRegex(BashExpertAdapterError, "input-must-be-object"):
            plugin.invoke("activation-2", "parse", "[]")

        deep = {}
        cursor = deep
        for _ in range(20):
            child = {}
            cursor["child"] = child
            cursor = child
        with self.assertRaisesRegex(BashExpertAdapterError, "input-structure-too-complex"):
            plugin.invoke("activation-2", "parse", json.dumps(deep))

        self.assertEqual(runtime.requests, [])


if __name__ == "__main__":
    unittest.main()
