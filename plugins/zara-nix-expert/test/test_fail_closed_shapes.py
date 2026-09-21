from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_nix_expert import NixExpertAdapterError, create_plugin
from zara_nix_expert.plugin import MANIFEST_DIGEST


ACTIVATION_ID = "act:" + ("e" * 32)


class RecordingRuntime:
    def __init__(self) -> None:
        self.resolved: list[str] = []
        self.requests: list[dict[str, object]] = []
        self.result_mutation: dict[str, object] = {}

    def resolve_capability(self, capability: str):
        self.resolved.append(capability)
        return object()

    def invoke_capability(self, _handle, request):
        self.requests.append(request)
        result = {
            "protocol": request["protocol"],
            "request_id": request["request_id"],
            "invocation_id": "inv:nix-fail-closed-shapes",
            "activation_id": request["activation_id"],
            "expert_id": request["expert_id"],
            "expert_version": "0.1.0",
            "manifest_digest": MANIFEST_DIGEST,
            "expert_operation": request["expert_operation"],
            "resolved_registry_generation": request["expected_registry_generation"],
            "resolved_runtime_generation": request["expected_runtime_generation"],
            "verdict": "succeeded",
            "data": {},
            "evidence_refs": ["flake.nix"],
            "usage": {"model_calls": 0},
            "effect_receipts": [],
        }
        result.update(self.result_mutation)
        return result


class NixExpertFailClosedShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = RecordingRuntime()
        self.plugin = create_plugin()
        self.plugin.start(self.runtime)

    def test_non_string_operation_is_adapter_error_before_host(self) -> None:
        for operation in ([], {}, 1, None):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(
                    NixExpertAdapterError, "unsupported-expert-operation"
                ):
                    self.plugin.invoke(
                        "req:nix-shape",
                        ACTIVATION_ID,
                        operation,
                        1,
                        1,
                        json.dumps({"path": "flake.nix"}),
                    )
        self.assertEqual(self.runtime.resolved, [])
        self.assertEqual(self.runtime.requests, [])

    def test_unhashable_host_verdict_fails_closed_without_fallback(self) -> None:
        self.runtime.result_mutation = {"verdict": []}
        with self.assertRaisesRegex(NixExpertAdapterError, "invalid-expert-verdict"):
            self.plugin.invoke(
                "req:nix-verdict",
                ACTIVATION_ID,
                "inspect_flake",
                1,
                1,
                json.dumps({"path": "flake.nix"}),
            )

        self.assertEqual(self.runtime.resolved, ["expert.invoke"])
        self.assertEqual(len(self.runtime.requests), 1)
        request = self.runtime.requests[0]
        self.assertEqual(request["limits"]["max_model_calls"], 0)


if __name__ == "__main__":
    unittest.main()
