from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_bash_expert import create_plugin
from zara_bash_expert.boundary import ZaraBashExpertBoundaryPlugin
from zara_bash_expert.plugin import BashExpertAdapterError, MANIFEST_DIGEST


ACTIVATION_ID = "act:" + ("d" * 32)


class RecordingRuntime:
    def __init__(self) -> None:
        self.resolved: list[str] = []
        self.requests: list[dict[str, object]] = []

    def resolve_capability(self, capability: str):
        self.resolved.append(capability)
        return object()

    def invoke_capability(self, _handle, request):
        self.requests.append(request)
        return {
            "protocol": request["protocol"],
            "request_id": request["request_id"],
            "invocation_id": "inv:bash-boundary",
            "activation_id": request["activation_id"],
            "expert_id": request["expert_id"],
            "expert_version": "0.1.0",
            "manifest_digest": MANIFEST_DIGEST,
            "expert_operation": request["expert_operation"],
            "resolved_registry_generation": request["expected_registry_generation"],
            "resolved_runtime_generation": request["expected_runtime_generation"],
            "verdict": "succeeded",
            "data": {},
            "evidence_refs": [".bashrc"],
            "usage": {"model_calls": 0},
            "effect_receipts": [],
        }


class BashExpertTypedBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = RecordingRuntime()
        self.plugin = ZaraBashExpertBoundaryPlugin()
        self.plugin.start(self.runtime)

    def invoke(self, operation: str, payload: object) -> str:
        return self.plugin.invoke(
            "req:bash-boundary",
            ACTIVATION_ID,
            operation,
            1,
            1,
            json.dumps(payload),
        )

    def test_public_factory_cannot_bypass_typed_boundary(self) -> None:
        self.assertIsInstance(create_plugin(), ZaraBashExpertBoundaryPlugin)

    def test_public_factory_exposes_no_parallel_expert_tools(self) -> None:
        plugin = create_plugin()
        self.assertEqual(plugin.tools(), ())

    def test_rejects_missing_extra_and_wrong_typed_fields_before_host(self) -> None:
        for payload, error in (
            ({}, "missing-required-input-field"),
            ({"path": ".bashrc", "argv": ["bash", "-c", "echo pwned"]}, "unexpected-input-field"),
            ({"path": {"value": ".bashrc"}}, "invalid-input-field-type"),
        ):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(BashExpertAdapterError, error):
                    self.invoke("inspect_startup", payload)
        self.assertEqual(self.runtime.resolved, [])
        self.assertEqual(self.runtime.requests, [])

    def test_rejects_empty_or_nul_paths_before_host(self) -> None:
        for path in ("", ".bashrc\x00ignored"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(BashExpertAdapterError, "invalid-input-path"):
                    self.invoke("inspect_startup", {"path": path})
        self.assertEqual(self.runtime.resolved, [])
        self.assertEqual(self.runtime.requests, [])

    def test_valid_typed_input_reaches_canonical_host_with_zero_model_limit(self) -> None:
        result = json.loads(self.invoke("inspect_startup", {"path": ".bashrc"}))
        self.assertEqual(self.runtime.resolved, ["expert.invoke"])
        self.assertEqual(len(self.runtime.requests), 1)
        request = self.runtime.requests[0]
        self.assertEqual(request["input"], {"path": ".bashrc"})
        self.assertEqual(request["limits"]["max_model_calls"], 0)
        self.assertEqual(result["usage"]["model_calls"], 0)
        self.assertEqual(result["effect_receipts"], [])


if __name__ == "__main__":
    unittest.main()
