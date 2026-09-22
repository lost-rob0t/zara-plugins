from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_nix_expert.plugin import NixExpertAdapterError, ZaraNixExpertPlugin


EXPECTED_MANIFEST_DIGEST = (
    "sha256:c5a71709af3cae413de5151dfc9fc1e2e19bcb9fb209ac6cc4c6815f381c3ef8"
)
ACTIVATION_ID = "act:" + ("a" * 32)


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
            "invocation_id": "inv:" + ("a" * 32),
            "activation_id": request["activation_id"],
            "expert_id": request["expert_id"],
            "expert_version": "1",
            "manifest_digest": EXPECTED_MANIFEST_DIGEST,
            "expert_operation": request["expert_operation"],
            "resolved_registry_generation": request["expected_registry_generation"],
            "resolved_runtime_generation": request["expected_runtime_generation"],
            "verdict": "succeeded",
            "data": {"verdict": "clean"},
            "evidence_refs": ["flake.nix"],
            "usage": {"model_calls": self.model_calls},
            "effect_receipts": self.effect_receipts,
        }


def invoke(
    plugin: ZaraNixExpertPlugin,
    operation: str = "inspect",
    payload: str = '{"source":"{}","source_generation":"fixture:nix:1"}',
) -> str:
    return plugin.invoke(
        "req-1",
        ACTIVATION_ID,
        operation,
        7,
        3,
        payload,
        timeout_ms=2500,
        max_results=8,
        max_output_bytes=32768,
    )


class NixExpertPluginTests(unittest.TestCase):
    def test_start_and_descriptor_match_current_zara_expert_contract(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraNixExpertPlugin()
        plugin.start(runtime)

        descriptor = json.loads(plugin.descriptor())

        self.assertEqual(descriptor["protocol"], "ZARA-EXPERT/1")
        self.assertEqual(descriptor["expert_id"], "zara:expert/nix")
        self.assertEqual(descriptor["expert_version"], "1")
        self.assertEqual(descriptor["manifest_digest"], EXPECTED_MANIFEST_DIGEST)
        self.assertEqual(descriptor["source_reference"], "dotfiles:.zara/experts/nix")
        self.assertEqual(descriptor["reasoning_kind"], "symbolic")
        self.assertEqual(descriptor["fallback_policy"], "fail_closed")
        self.assertEqual(descriptor["delegation_policy"], "never")
        self.assertEqual(descriptor["possible_effects"], ["filesystem_write"])
        self.assertEqual(descriptor["supported_engines"], ["swipl"])
        self.assertEqual(
            descriptor["applicability"],
            {"keywords": ["nix", "nixos", "flake", "home-manager"]},
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
                "match",
                "inspect",
                "diagnose",
                "repair.preview",
                "repair.verify",
                "style.rules",
                "explain",
                "repair.apply",
            },
        )
        for operation in descriptor["operations"]:
            self.assertEqual(set(operation), {"operation_id", "input_schema", "output_schema"})
            self.assertIsInstance(operation["input_schema"]["fields"], list)
            self.assertIsInstance(operation["output_schema"]["fields"], list)
            self.assertTrue(operation["output_schema"]["fields"])
        self.assertEqual(runtime.resolved, [])
        self.assertEqual(runtime.requests, [])

    def test_read_only_invocation_uses_canonical_envelope_and_zero_model_limit(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraNixExpertPlugin()
        plugin.start(runtime)

        result = json.loads(
            invoke(
                plugin,
                "inspect",
                '{"source":"{}","source_generation":"fixture:nix:1"}',
            )
        )

        self.assertEqual(runtime.resolved, ["expert.invoke"])
        self.assertEqual(len(runtime.requests), 1)
        request = runtime.requests[0]
        self.assertEqual(request["protocol"], "ZARA-EXPERT/1")
        self.assertEqual(request["request_id"], "req-1")
        self.assertEqual(request["activation_id"], ACTIVATION_ID)
        self.assertEqual(request["expert_id"], "zara:expert/nix")
        self.assertEqual(request["expert_operation"], "inspect")
        self.assertEqual(request["expected_registry_generation"], 7)
        self.assertEqual(request["expected_runtime_generation"], 3)
        self.assertEqual(request["limits"]["max_model_calls"], 0)
        self.assertEqual(result["usage"]["model_calls"], 0)
        self.assertEqual(result["effect_receipts"], [])

    def test_unknown_operation_is_rejected_before_host(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraNixExpertPlugin()
        plugin.start(runtime)

        with self.assertRaisesRegex(NixExpertAdapterError, "unsupported-expert-operation"):
            invoke(plugin, "build")

        self.assertEqual(runtime.resolved, [])
        self.assertEqual(runtime.requests, [])

    def test_operation_input_schema_rejects_malformed_payload_before_host(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraNixExpertPlugin()
        plugin.start(runtime)

        cases = (
            ("inspect", '{"source":"{}"}', "missing-operation-input"),
            (
                "inspect",
                '{"source":"{}","source_generation":"fixture:1","provider_fallback":true}',
                "unknown-operation-input",
            ),
            (
                "inspect",
                '{"source":7,"source_generation":"fixture:1"}',
                "invalid-operation-input",
            ),
        )
        for operation, payload, error in cases:
            with self.subTest(operation=operation, error=error):
                with self.assertRaisesRegex(NixExpertAdapterError, error):
                    invoke(plugin, operation, payload)

        self.assertEqual(runtime.resolved, [])
        self.assertEqual(runtime.requests, [])

    def test_invalid_generation_or_limit_is_rejected_before_host(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraNixExpertPlugin()
        plugin.start(runtime)

        with self.assertRaisesRegex(NixExpertAdapterError, "invalid-registry-generation"):
            plugin.invoke("req-1", ACTIVATION_ID, "inspect", -1, 1)
        with self.assertRaisesRegex(NixExpertAdapterError, "invalid-max-results"):
            plugin.invoke("req-1", ACTIVATION_ID, "inspect", 1, 1, max_results=33)

        self.assertEqual(runtime.requests, [])

    def test_generation_and_limit_wire_values_require_builtin_integers(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraNixExpertPlugin()
        plugin.start(runtime)

        cases = (
            ({"expected_registry_generation": 0.0}, "invalid-registry-generation"),
            ({"expected_runtime_generation": 0.0}, "invalid-runtime-generation"),
            ({"timeout_ms": 2500.0}, "invalid-timeout-ms"),
            ({"max_results": 8.0}, "invalid-max-results"),
            ({"max_output_bytes": 32768.0}, "invalid-max-output-bytes"),
        )
        for overrides, error in cases:
            arguments = {
                "request_id": "req:zero",
                "activation_id": ACTIVATION_ID,
                "expert_operation": "inspect",
                "expected_registry_generation": 0,
                "expected_runtime_generation": 0,
                "input_json": '{"source":"{}","source_generation":"fixture:nix:1"}',
                "timeout_ms": 2500,
                "max_results": 8,
                "max_output_bytes": 32768,
            }
            arguments.update(overrides)
            with self.subTest(error=error):
                with self.assertRaisesRegex(NixExpertAdapterError, error):
                    plugin.invoke(**arguments)

        with self.assertRaisesRegex(NixExpertAdapterError, "invalid-registry-generation"):
            plugin.invoke("req-1", ACTIVATION_ID, "inspect", True, 1)
        with self.assertRaisesRegex(NixExpertAdapterError, "invalid-runtime-generation"):
            plugin.invoke("req-1", ACTIVATION_ID, "inspect", 1, 1.5)

        self.assertEqual(runtime.requests, [])

    def test_noncanonical_activation_id_is_rejected_before_host(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraNixExpertPlugin()
        plugin.start(runtime)

        with self.assertRaisesRegex(NixExpertAdapterError, "invalid-activation-id"):
            plugin.invoke("req-1", "activation-1", "inspect", 1, 1)

        self.assertEqual(runtime.requests, [])

    def test_missing_composition_fails_closed_without_fallback(self) -> None:
        plugin = ZaraNixExpertPlugin()
        plugin.start(object())

        with self.assertRaisesRegex(NixExpertAdapterError, "expert-host-composition-unavailable"):
            invoke(plugin)

    def test_nonzero_or_missing_model_usage_is_rejected(self) -> None:
        plugin = ZaraNixExpertPlugin()
        plugin.start(FakeRuntime(model_calls=1))
        with self.assertRaisesRegex(NixExpertAdapterError, "zero-model-proof-missing"):
            invoke(plugin)

        class MissingUsageRuntime(FakeRuntime):
            def invoke_capability(self, handle, request):
                result = super().invoke_capability(handle, request)
                result.pop("usage")
                return result

        plugin.start(MissingUsageRuntime())
        with self.assertRaisesRegex(NixExpertAdapterError, "zero-model-proof-missing"):
            invoke(plugin)

    def test_read_only_result_with_effect_receipt_is_rejected(self) -> None:
        plugin = ZaraNixExpertPlugin()
        plugin.start(FakeRuntime(effect_receipts=[{"effect": "filesystem_read"}]))

        with self.assertRaisesRegex(NixExpertAdapterError, "read-only-effect-leak"):
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
                result["activation_id"] = "act:" + ("b" * 32)
                return result

        plugin = ZaraNixExpertPlugin()
        plugin.start(StaleRuntime())
        with self.assertRaisesRegex(NixExpertAdapterError, "stale-expert-result"):
            invoke(plugin)

        plugin.start(ForgedRuntime())
        with self.assertRaisesRegex(NixExpertAdapterError, "expert-result-identity-mismatch"):
            invoke(plugin)

    def test_invalid_or_deep_input_never_reaches_host(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraNixExpertPlugin()
        plugin.start(runtime)

        with self.assertRaisesRegex(NixExpertAdapterError, "input-must-be-object"):
            invoke(plugin, payload="[]")

        deep = {}
        cursor = deep
        for _ in range(20):
            child = {}
            cursor["child"] = child
            cursor = child
        with self.assertRaisesRegex(NixExpertAdapterError, "input-structure-too-complex"):
            invoke(plugin, payload=json.dumps(deep))

        self.assertEqual(runtime.requests, [])


if __name__ == "__main__":
    unittest.main()
