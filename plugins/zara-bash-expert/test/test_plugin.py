from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_bash_expert.plugin import BashExpertAdapterError, ZaraBashExpertPlugin


EXPECTED_MANIFEST_DIGEST = (
    "sha256:7aaa1208e53a6a863482f4735273928ee295fe0b4581a5e359c3bf8647cdc13a"
)
ACTIVATION_ID = "act:" + ("b" * 32)


class FakeRuntime:
    def __init__(self, *, model_calls: int = 0, effect_receipts=None) -> None:
        self.model_calls = model_calls
        self.effect_receipts = [] if effect_receipts is None else effect_receipts
        self.resolved = []
        self.requests = []

    def resolve_capability(self, capability: str):
        self.resolved.append(capability)
        return object()

    def invoke_capability(self, handle, request):
        self.requests.append(request)
        return {
            "protocol": request["protocol"],
            "request_id": request["request_id"],
            "invocation_id": "inv:test-bash",
            "activation_id": request["activation_id"],
            "expert_id": request["expert_id"],
            "expert_version": "0.1.0",
            "manifest_digest": EXPECTED_MANIFEST_DIGEST,
            "expert_operation": request["expert_operation"],
            "resolved_registry_generation": request["expected_registry_generation"],
            "resolved_runtime_generation": request["expected_runtime_generation"],
            "verdict": "succeeded",
            "data": {"verdict": "clean"},
            "evidence_refs": [".bashrc"],
            "usage": {"model_calls": self.model_calls},
            "effect_receipts": self.effect_receipts,
        }


def invoke(
    plugin: ZaraBashExpertPlugin,
    operation: str = "parse",
    payload: str = '{"source":"echo ok"}',
) -> str:
    return plugin.invoke(
        "req-2",
        ACTIVATION_ID,
        operation,
        7,
        3,
        payload,
        timeout_ms=2500,
        max_results=8,
        max_output_bytes=32768,
    )


class BashExpertPluginTests(unittest.TestCase):
    def test_start_and_descriptor_match_current_zara_expert_contract(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraBashExpertPlugin()
        plugin.start(runtime)

        descriptor = json.loads(plugin.descriptor())

        self.assertEqual(descriptor["protocol"], "ZARA-EXPERT/1")
        self.assertEqual(descriptor["expert_id"], "zara:expert/bash")
        self.assertEqual(descriptor["manifest_digest"], EXPECTED_MANIFEST_DIGEST)
        self.assertEqual(descriptor["source_reference"], "source:dotfiles-bash-expert-v1")
        self.assertEqual(descriptor["reasoning_kind"], "symbolic")
        self.assertEqual(descriptor["fallback_policy"], "fail_closed")
        self.assertEqual(descriptor["delegation_policy"], "never")
        self.assertEqual(descriptor["possible_effects"], ["none"])
        self.assertEqual(descriptor["supported_engines"], ["swipl"])
        self.assertEqual(
            descriptor["applicability"],
            {"keywords": ["bash", "bashrc", "quoting", "shell"]},
        )
        self.assertNotIn("placement", descriptor)
        self.assertNotIn("required_observations", descriptor)
        self.assertNotIn("applicability_schema", descriptor)
        self.assertEqual(descriptor["availability"], "unavailable")
        self.assertEqual(
            descriptor["unavailable_reason"],
            "canonical-source-or-host-not-activated",
        )
        self.assertEqual(descriptor["resource_limits"]["max_model_calls"], 0)
        self.assertEqual(
            {operation["operation_id"] for operation in descriptor["operations"]},
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
            self.assertEqual(set(operation), {"operation_id", "input_schema", "output_schema"})
            self.assertIsInstance(operation["input_schema"]["fields"], list)
            self.assertEqual(operation["output_schema"], {"fields": []})
        self.assertEqual(runtime.resolved, [])
        self.assertEqual(runtime.requests, [])

    def test_read_only_invocation_uses_canonical_envelope_and_zero_model_limit(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraBashExpertPlugin()
        plugin.start(runtime)

        result = json.loads(
            invoke(plugin, "inspect_source_graph", '{"path":".bashrc"}')
        )

        self.assertEqual(runtime.resolved, ["expert.invoke"])
        self.assertEqual(len(runtime.requests), 1)
        request = runtime.requests[0]
        self.assertEqual(request["protocol"], "ZARA-EXPERT/1")
        self.assertEqual(request["request_id"], "req-2")
        self.assertEqual(request["activation_id"], ACTIVATION_ID)
        self.assertEqual(request["expert_id"], "zara:expert/bash")
        self.assertEqual(request["expert_operation"], "inspect_source_graph")
        self.assertEqual(request["expected_registry_generation"], 7)
        self.assertEqual(request["expected_runtime_generation"], 3)
        self.assertEqual(request["limits"]["max_model_calls"], 0)
        self.assertEqual(result["usage"]["model_calls"], 0)
        self.assertEqual(result["effect_receipts"], [])

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
            plugin.invoke("req-2", ACTIVATION_ID, "parse", 1, False)
        with self.assertRaisesRegex(BashExpertAdapterError, "invalid-timeout-ms"):
            plugin.invoke("req-2", ACTIVATION_ID, "parse", 1, 1, timeout_ms=3001)

        self.assertEqual(runtime.requests, [])

    def test_generation_zero_and_integral_json_numbers_are_canonical(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraBashExpertPlugin()
        plugin.start(runtime)

        plugin.invoke(
            "req:zero",
            ACTIVATION_ID,
            "parse",
            0.0,
            0.0,
            '{"source":"echo ok"}',
            timeout_ms=2500.0,
            max_results=8.0,
            max_output_bytes=32768.0,
        )
        request = runtime.requests[-1]
        self.assertEqual(request["expected_registry_generation"], 0)
        self.assertEqual(request["expected_runtime_generation"], 0)
        self.assertIs(type(request["limits"]["timeout_ms"]), int)

        with self.assertRaisesRegex(BashExpertAdapterError, "invalid-registry-generation"):
            plugin.invoke("req-2", ACTIVATION_ID, "parse", True, 1)
        with self.assertRaisesRegex(BashExpertAdapterError, "invalid-runtime-generation"):
            plugin.invoke("req-2", ACTIVATION_ID, "parse", 1, 1.5)

        self.assertEqual(len(runtime.requests), 1)

    def test_noncanonical_activation_id_is_rejected_before_host(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraBashExpertPlugin()
        plugin.start(runtime)

        with self.assertRaisesRegex(BashExpertAdapterError, "invalid-activation-id"):
            plugin.invoke("req-2", "activation-2", "parse", 1, 1)

        self.assertEqual(runtime.requests, [])

    def test_missing_composition_fails_closed_without_shell_or_model_fallback(self) -> None:
        plugin = ZaraBashExpertPlugin()
        plugin.start(object())

        with self.assertRaisesRegex(BashExpertAdapterError, "expert-host-composition-unavailable"):
            invoke(plugin)

    def test_nonzero_or_missing_model_usage_is_rejected(self) -> None:
        plugin = ZaraBashExpertPlugin()
        plugin.start(FakeRuntime(model_calls=1))
        with self.assertRaisesRegex(BashExpertAdapterError, "zero-model-proof-missing"):
            invoke(plugin)

        class MissingUsageRuntime(FakeRuntime):
            def invoke_capability(self, handle, request):
                result = super().invoke_capability(handle, request)
                result.pop("usage")
                return result

        plugin.start(MissingUsageRuntime())
        with self.assertRaisesRegex(BashExpertAdapterError, "zero-model-proof-missing"):
            invoke(plugin)

    def test_read_only_result_with_effect_receipt_is_rejected(self) -> None:
        plugin = ZaraBashExpertPlugin()
        plugin.start(FakeRuntime(effect_receipts=[{"effect": "filesystem_read"}]))

        with self.assertRaisesRegex(BashExpertAdapterError, "read-only-effect-leak"):
            invoke(plugin)

    def test_stale_or_forged_result_is_rejected(self) -> None:
        class StaleRuntime(FakeRuntime):
            def invoke_capability(self, handle, request):
                result = super().invoke_capability(handle, request)
                result["resolved_runtime_generation"] = request["expected_runtime_generation"] + 1
                return result

        class ForgedRuntime(FakeRuntime):
            def invoke_capability(self, handle, request):
                result = super().invoke_capability(handle, request)
                result["expert_id"] = "zara:expert/nix"
                return result

        plugin = ZaraBashExpertPlugin()
        plugin.start(StaleRuntime())
        with self.assertRaisesRegex(BashExpertAdapterError, "stale-expert-result"):
            invoke(plugin)

        plugin.start(ForgedRuntime())
        with self.assertRaisesRegex(BashExpertAdapterError, "expert-result-identity-mismatch"):
            invoke(plugin)

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
