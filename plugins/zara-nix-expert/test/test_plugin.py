from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_nix_expert.plugin import NixExpertAdapterError, ZaraNixExpertPlugin


EXPECTED_MANIFEST_DIGEST = (
    "sha256:79ed16fd0c6100baefdd6ce562296ef99d9dc51fb7f90935888f9860ccb6e140"
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
            "evidence": [{"kind": "source", "ref": "flake.nix"}],
            "usage": {"model_calls": self.model_calls},
            "side_effect_receipts": self.side_effect_receipts,
        }


def invoke(plugin: ZaraNixExpertPlugin, operation: str = "parse", payload: str = "{}") -> str:
    return plugin.invoke(
        "req-1",
        "activation-1",
        operation,
        7,
        3,
        payload,
        timeout_ms=2500,
        max_results=8,
        max_output_bytes=32768,
    )


class NixExpertPluginTests(unittest.TestCase):
    def test_start_and_descriptor_are_passive_zero_model_and_schema_shaped(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraNixExpertPlugin()
        plugin.start(runtime)

        descriptor = json.loads(plugin.descriptor())

        self.assertEqual(descriptor["protocol"], "ZARA-EXPERT/1")
        self.assertEqual(descriptor["expert_id"], "zara:expert/nix")
        self.assertEqual(descriptor["manifest_digest"], EXPECTED_MANIFEST_DIGEST)
        self.assertEqual(descriptor["source_reference"], "source:dotfiles-nix-expert-v1")
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
                "inspect_flake",
                "inspect_module",
                "inspect_home_manager",
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
        plugin = ZaraNixExpertPlugin()
        plugin.start(runtime)

        result = json.loads(invoke(plugin, "inspect_flake", '{"path":"flake.nix"}'))

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
        self.assertEqual(request["request_id"], "req-1")
        self.assertEqual(request["expert_id"], "zara:expert/nix")
        self.assertEqual(request["expert_operation"], "inspect_flake")
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
        plugin = ZaraNixExpertPlugin()
        plugin.start(runtime)

        with self.assertRaisesRegex(NixExpertAdapterError, "unsupported-expert-operation"):
            invoke(plugin, "build")

        self.assertEqual(runtime.resolved, [])
        self.assertEqual(runtime.requests, [])

    def test_invalid_generation_or_limit_is_rejected_before_host(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraNixExpertPlugin()
        plugin.start(runtime)

        with self.assertRaisesRegex(NixExpertAdapterError, "invalid-registry-generation"):
            plugin.invoke("req-1", "activation-1", "parse", 0, 1)
        with self.assertRaisesRegex(NixExpertAdapterError, "invalid-max-results"):
            plugin.invoke("req-1", "activation-1", "parse", 1, 1, max_results=33)

        self.assertEqual(runtime.requests, [])

    def test_json_integer_semantics_match_zara_expert_schema(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraNixExpertPlugin()
        plugin.start(runtime)

        plugin.invoke(
            "req-1",
            "activation-1",
            "parse",
            7.0,
            3.0,
            timeout_ms=2500.0,
            max_results=8.0,
            max_output_bytes=32768.0,
        )
        request = runtime.requests[-1]
        self.assertIs(type(request["expected_registry_generation"]), int)
        self.assertIs(type(request["expected_runtime_generation"]), int)
        self.assertIs(type(request["limits"]["timeout_ms"]), int)
        self.assertIs(type(request["limits"]["max_results"]), int)
        self.assertIs(type(request["limits"]["max_output_bytes"]), int)

        with self.assertRaisesRegex(NixExpertAdapterError, "invalid-registry-generation"):
            plugin.invoke("req-1", "activation-1", "parse", True, 1)
        with self.assertRaisesRegex(NixExpertAdapterError, "invalid-runtime-generation"):
            plugin.invoke("req-1", "activation-1", "parse", 1, 1.5)
        with self.assertRaisesRegex(NixExpertAdapterError, "invalid-timeout-ms"):
            plugin.invoke("req-1", "activation-1", "parse", 1, 1, timeout_ms=1.5)

        self.assertEqual(len(runtime.requests), 1)

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
                self.requests.append(request)
                return {
                    "status": "succeeded",
                    "data": {},
                    "side_effect_receipts": [],
                }

        plugin.start(MissingUsageRuntime())
        with self.assertRaisesRegex(NixExpertAdapterError, "zero-model-proof-missing"):
            invoke(plugin)

    def test_read_only_result_with_effect_receipt_is_rejected(self) -> None:
        plugin = ZaraNixExpertPlugin()
        plugin.start(FakeRuntime(side_effect_receipts=[{"effect": "nix.eval"}]))

        with self.assertRaisesRegex(NixExpertAdapterError, "read-only-effect-leak"):
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
