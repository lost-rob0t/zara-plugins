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

    def test_read_only_invocation_uses_canonical_capability_and_zero_model_limit(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraNixExpertPlugin()
        plugin.start(runtime)

        result = json.loads(
            plugin.invoke("activation-1", "inspect_flake", '{"path":"flake.nix"}')
        )

        self.assertEqual(runtime.resolved, ["expert.invoke"])
        self.assertEqual(len(runtime.requests), 1)
        request = runtime.requests[0]
        self.assertEqual(request["protocol"], "ZARA-EXPERT/1")
        self.assertEqual(request["expert_id"], "zara:expert/nix")
        self.assertEqual(request["expert_operation"], "inspect_flake")
        self.assertEqual(request["limits"]["max_model_calls"], 0)
        self.assertEqual(request["effect_policy"], "deny")
        self.assertEqual(result["usage"]["model_calls"], 0)
        self.assertEqual(result["side_effect_receipts"], [])

    def test_effectful_or_unknown_operation_is_rejected_before_host(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraNixExpertPlugin()
        plugin.start(runtime)

        with self.assertRaisesRegex(NixExpertAdapterError, "unsupported-expert-operation"):
            plugin.invoke("activation-1", "build", "{}")

        self.assertEqual(runtime.resolved, [])
        self.assertEqual(runtime.requests, [])

    def test_missing_composition_fails_closed_without_fallback(self) -> None:
        plugin = ZaraNixExpertPlugin()
        plugin.start(object())

        with self.assertRaisesRegex(NixExpertAdapterError, "expert-host-composition-unavailable"):
            plugin.invoke("activation-1", "parse", "{}")

    def test_nonzero_or_missing_model_usage_is_rejected(self) -> None:
        plugin = ZaraNixExpertPlugin()
        plugin.start(FakeRuntime(model_calls=1))
        with self.assertRaisesRegex(NixExpertAdapterError, "zero-model-proof-missing"):
            plugin.invoke("activation-1", "parse", "{}")

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
            plugin.invoke("activation-1", "parse", "{}")

    def test_read_only_result_with_effect_receipt_is_rejected(self) -> None:
        plugin = ZaraNixExpertPlugin()
        plugin.start(FakeRuntime(side_effect_receipts=[{"effect": "nix.eval"}]))

        with self.assertRaisesRegex(NixExpertAdapterError, "read-only-effect-leak"):
            plugin.invoke("activation-1", "parse", "{}")

    def test_invalid_or_deep_input_never_reaches_host(self) -> None:
        runtime = FakeRuntime()
        plugin = ZaraNixExpertPlugin()
        plugin.start(runtime)

        with self.assertRaisesRegex(NixExpertAdapterError, "input-must-be-object"):
            plugin.invoke("activation-1", "parse", "[]")

        deep = {}
        cursor = deep
        for _ in range(20):
            child = {}
            cursor["child"] = child
            cursor = child
        with self.assertRaisesRegex(NixExpertAdapterError, "input-structure-too-complex"):
            plugin.invoke("activation-1", "parse", json.dumps(deep))

        self.assertEqual(runtime.requests, [])


if __name__ == "__main__":
    unittest.main()
