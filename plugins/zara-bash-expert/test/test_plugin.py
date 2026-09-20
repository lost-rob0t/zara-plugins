from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_bash_expert.plugin import BashExpertAdapterError, ZaraBashExpertPlugin


EXPECTED_MANIFEST_DIGEST = (
    "sha256:a09f376755aa3c83c1fc30133d08d3ac4cad7638e26fb5e7f95713beca597f3e"
)


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


def invoke(plugin: ZaraBashExpertPlugin, operation: str = "parse", payload: str = "{}") -> str:
    return plugin.invoke(
        "req-2",
        "activation-2",
        operation,
        7,
        3,
        payload,
        timeout_ms=2500,
        max_results=8,
        max_output_bytes=32768,
    )


class BashExpertPluginTests(unittest.TestCase):
    def test_start_and_descriptor_are_passive_zero_model_and_schema_shaped(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraBashExpertPlugin()
        plugin.start(runtime)

        descriptor = json.loads(plugin.descriptor())

        self.assertEqual(descriptor["protocol"], "ZARA-EXPERT/1")
        self.assertEqual(descriptor["expert_id"], "zara:expert/bash")
        self.assertEqual(descriptor["manifest_digest"], EXPECTED_MANIFEST_DIGEST)
        self.assertEqual(descriptor["source_reference"], "source:dotfiles-bash-expert-v1")
        self.assertEqual(descriptor["reasoning_kind"], "symbolic")
        self.assertEqual(descriptor["fallback_policy"], "none")
        self.assertEqual(descriptor["delegation_policy"], "none")
        self.assertEqual(descriptor["availability"], "unavailable")
        self.assertEqual(
            descriptor["unavailable_reason"],
            "canonical-source-or-host-not-activated",
        )
        self.assertEqual(
            descriptor["resource_limits"],
            {
                "timeout_ms": 3000,
                "max_results": 32,
                "max_output_bytes": 65536,
                "max_model_calls": 0,
            },
        )
        self.assertEqual(
            {operation["id"] for operation in descriptor["operations"]},
            {
                "parse",
                "inspect_startup",
                "inspect_source_graph",
                "diagnose_quoting",
                "style_check",
                "check_plan",
            },
        )
        for operation in descriptor["operations"]:
            self.assertEqual(operation["effects"], [])
            self.assertEqual(operation["required_capabilities"], ["expert.invoke"])
            self.assertTrue(operation["input_schema"].startswith("schema:"))
            self.assertTrue(operation["output_schema"].startswith("schema:"))
        self.assertEqual(runtime.resolved, [])
        self.assertEqual(runtime.requests, [])

    def test_read_only_invocation_uses_exact_canonical_envelope_and_zero_model_limit(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraBashExpertPlugin()
        plugin.start(runtime)

        result = json.loads(
            invoke(plugin, "inspect_source_graph", '{"path":".bashrc"}')
        )

        self.assertEqual(runtime.resolved, ["expert.invoke"])
        self.assertEqual(len(runtime.requests), 1)
        request = runtime.requests[0]
        self.assertEqual(
            set(request),
            {
                "protocol",
                "request_id",
                "operation",
                "activation_id",
                "expert_id",
                "expert_operation",
                "expected_registry_generation",
                "expected_runtime_generation",
                "input",
                "limits",
            },
        )
        self.assertEqual(request["protocol"], "ZARA-EXPERT/1")
        self.assertEqual(request["request_id"], "req-2")
        self.assertEqual(request["expert_id"], "zara:expert/bash")
        self.assertEqual(request["expert_operation"], "inspect_source_graph")
        self.assertEqual(request["expected_registry_generation"], 7)
        self.assertEqual(request["expected_runtime_generation"], 3)
        self.assertEqual(
            request["limits"],
            {
                "timeout_ms": 2500,
                "max_results": 8,
                "max_output_bytes": 32768,
                "max_model_calls": 0,
            },
        )
        self.assertEqual(result["usage"]["model_calls"], 0)
        self.assertEqual(result["side_effect_receipts"], [])

    def test_effectful_or_unknown_operation_is_rejected_before_host(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraBashExpertPlugin()
        plugin.start(runtime)

        with self.assertRaisesRegex(BashExpertAdapterError, "unsupported-expert-operation"):
            invoke(plugin, "execute")

        self.assertEqual(runtime.resolved, [])
        self.assertEqual(runtime.requests, [])

    def test_invalid_generation_or_limit_is_rejected_before_host(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraBashExpertPlugin()
        plugin.start(runtime)

        with self.assertRaisesRegex(BashExpertAdapterError, "invalid-runtime-generation"):
            plugin.invoke("req-2", "activation-2", "parse", 1, False)
        with self.assertRaisesRegex(BashExpertAdapterError, "invalid-timeout-ms"):
            plugin.invoke("req-2", "activation-2", "parse", 1, 1, timeout_ms=3001)

        self.assertEqual(runtime.requests, [])

    def test_missing_composition_fails_closed_without_shell_or_model_fallback(self) -> None:
        plugin = ZaraBashExpertPlugin()
        plugin.start(object())

        with self.assertRaisesRegex(BashExpertAdapterError, "expert-host-composition-unavailable"):
            invoke(plugin, payload='{"source":"echo ok"}')

    def test_nonzero_or_missing_model_usage_is_rejected(self) -> None:
        plugin = ZaraBashExpertPlugin()
        plugin.start(FakeRuntime(model_calls=1))
        with self.assertRaisesRegex(BashExpertAdapterError, "zero-model-proof-missing"):
            invoke(plugin, payload='{"source":"echo ok"}')

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
            invoke(plugin, payload='{"source":"echo ok"}')

    def test_read_only_result_with_effect_receipt_is_rejected(self) -> None:
        plugin = ZaraBashExpertPlugin()
        plugin.start(FakeRuntime(side_effect_receipts=[{"effect": "bash.execute"}]))

        with self.assertRaisesRegex(BashExpertAdapterError, "read-only-effect-leak"):
            invoke(plugin, payload='{"source":"echo ok"}')

    def test_invalid_or_deep_input_never_reaches_host(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraBashExpertPlugin()
        plugin.start(runtime)

        with self.assertRaisesRegex(BashExpertAdapterError, "input-must-be-object"):
            invoke(plugin, payload="[]")

        deep = {}
        cursor = deep
        for _ in range(20):
            child = {}
            cursor["child"] = child
            cursor = child
        with self.assertRaisesRegex(BashExpertAdapterError, "input-structure-too-complex"):
            invoke(plugin, payload=json.dumps(deep))

        self.assertEqual(runtime.requests, [])


if __name__ == "__main__":
    unittest.main()
