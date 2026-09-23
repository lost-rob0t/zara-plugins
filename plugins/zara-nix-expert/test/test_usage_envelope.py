from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_nix_expert.plugin import NixExpertAdapterError, ZaraNixExpertPlugin


ACTIVATION_ID = "act:" + ("a" * 32)
MANIFEST_DIGEST = "sha256:c5a71709af3cae413de5151dfc9fc1e2e19bcb9fb209ac6cc4c6815f381c3ef8"


class UsageRuntime:
    def __init__(self, usage: object) -> None:
        self.usage = usage

    def resolve_capability(self, capability: str):
        if capability != "expert.invoke":
            raise AssertionError(capability)
        return object()

    def invoke_capability(self, handle, request):
        return {
            "protocol": request["protocol"],
            "request_id": request["request_id"],
            "invocation_id": "inv:" + ("a" * 32),
            "activation_id": request["activation_id"],
            "expert_id": request["expert_id"],
            "expert_version": "1",
            "manifest_digest": MANIFEST_DIGEST,
            "expert_operation": request["expert_operation"],
            "resolved_registry_generation": request["expected_registry_generation"],
            "resolved_runtime_generation": request["expected_runtime_generation"],
            "verdict": "succeeded",
            "data": {"verdict": "clean"},
            "evidence_refs": ["flake.nix"],
            "usage": self.usage,
            "effect_receipts": [],
        }


def invoke_with_usage(usage: object) -> None:
    plugin = ZaraNixExpertPlugin()
    plugin.start(UsageRuntime(usage))
    plugin.invoke(
        "req-usage",
        ACTIVATION_ID,
        "inspect",
        7,
        3,
        '{"source":"{}","source_generation":"fixture:nix:1"}',
        timeout_ms=2500,
        max_results=8,
        max_output_bytes=32768,
    )


class UsageEnvelopeTests(unittest.TestCase):
    def test_provider_shaped_or_unknown_usage_fields_fail_closed(self) -> None:
        cases = (
            {"model_calls": 0, "provider_calls": 0},
            {"model_calls": 0, "provider": "hidden"},
            {"model_calls": 0, "tokens": 1},
            {"model_calls": 0, 7: "forged"},
        )
        for usage in cases:
            with self.subTest(usage=usage):
                with self.assertRaisesRegex(
                    NixExpertAdapterError,
                    "unknown-expert-usage-field",
                ):
                    invoke_with_usage(usage)

    def test_usage_must_be_plain_json_object(self) -> None:
        class UsageDict(dict):
            pass

        for usage in (UsageDict(model_calls=0), [("model_calls", 0)]):
            with self.subTest(usage_type=type(usage).__name__):
                with self.assertRaisesRegex(
                    NixExpertAdapterError,
                    "invalid-expert-usage",
                ):
                    invoke_with_usage(usage)


if __name__ == "__main__":
    unittest.main()
