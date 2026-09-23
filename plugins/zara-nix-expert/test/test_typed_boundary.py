from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import zara_nix_expert
from zara_nix_expert import create_plugin
from zara_nix_expert.boundary import ZaraNixExpertBoundaryPlugin
from zara_nix_expert.plugin import MANIFEST_DIGEST, NixExpertAdapterError


ACTIVATION_ID = "act:" + ("c" * 32)
MATCH_PAYLOAD = {"path": "flake.nix", "source_generation": "fixture:nix:1"}


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
            "invocation_id": "inv:" + ("a" * 32),
            "activation_id": request["activation_id"],
            "expert_id": request["expert_id"],
            "expert_version": "1",
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


class NixExpertTypedBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = RecordingRuntime()
        self.plugin = ZaraNixExpertBoundaryPlugin()
        self.plugin.start(self.runtime)

    def invoke(self, operation: str, payload: object) -> str:
        return self.plugin.invoke(
            "req:nix-boundary",
            ACTIVATION_ID,
            operation,
            1,
            1,
            json.dumps(payload),
        )

    def test_public_factory_cannot_bypass_typed_boundary(self) -> None:
        self.assertIsInstance(create_plugin(), ZaraNixExpertBoundaryPlugin)

    def test_public_factory_exposes_no_parallel_expert_tools(self) -> None:
        plugin = create_plugin()
        self.assertEqual(plugin.tools(), ())

    def test_package_root_does_not_export_untyped_adapter(self) -> None:
        self.assertFalse(hasattr(zara_nix_expert, "ZaraNixExpertPlugin"))
        self.assertNotIn("ZaraNixExpertPlugin", zara_nix_expert.__all__)

    def test_rejects_missing_extra_and_wrong_typed_fields_before_host(self) -> None:
        for payload, error in (
            ({}, "missing-required-input-field"),
            (
                {
                    "path": "flake.nix",
                    "source_generation": "fixture:nix:1",
                    "command": "nix build",
                },
                "unexpected-input-field",
            ),
            (
                {"path": ["flake.nix"], "source_generation": "fixture:nix:1"},
                "invalid-input-field-type",
            ),
            (
                {"path": "flake.nix", "source_generation": {"bad": True}},
                "invalid-input-field-type",
            ),
        ):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(NixExpertAdapterError, error):
                    self.invoke("match", payload)
        self.assertEqual(self.runtime.resolved, [])
        self.assertEqual(self.runtime.requests, [])

    def test_rejects_empty_or_nul_paths_before_host(self) -> None:
        for path in ("", "flake.nix\x00ignored"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(NixExpertAdapterError, "invalid-input-path"):
                    self.invoke(
                        "match",
                        {"path": path, "source_generation": "fixture:nix:1"},
                    )
        self.assertEqual(self.runtime.resolved, [])
        self.assertEqual(self.runtime.requests, [])

    def test_rejects_forged_generation_types_from_canonical_host(self) -> None:
        cases = (
            ("resolved_registry_generation", True),
            ("resolved_registry_generation", 1.0),
            ("resolved_runtime_generation", True),
            ("resolved_runtime_generation", 1.0),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                self.runtime.result_mutation = {field: value}
                with self.assertRaisesRegex(NixExpertAdapterError, "stale-expert-result"):
                    self.invoke("match", MATCH_PAYLOAD)
                request = self.runtime.requests[-1]
                self.assertIs(type(request["expected_registry_generation"]), int)
                self.assertIs(type(request["expected_runtime_generation"]), int)
                self.assertEqual(request["limits"]["max_model_calls"], 0)
        self.assertEqual(self.runtime.resolved, ["expert.invoke"] * len(cases))
        self.assertEqual(len(self.runtime.requests), len(cases))

    def test_cancelled_result_rejects_late_output(self) -> None:
        cases = (
            {"data": {"late": "flake result"}},
            {"evidence_refs": ["ev:late-nix"]},
        )
        for mutation in cases:
            with self.subTest(mutation=mutation):
                self.runtime.result_mutation = {
                    "verdict": "cancelled",
                    "data": {},
                    "evidence_refs": [],
                    **mutation,
                }
                with self.assertRaisesRegex(
                    NixExpertAdapterError, "cancelled-expert-output-leak"
                ):
                    self.invoke("match", MATCH_PAYLOAD)
                request = self.runtime.requests[-1]
                self.assertEqual(request["limits"]["max_model_calls"], 0)
        self.assertEqual(len(self.runtime.requests), len(cases))

    def test_clean_cancelled_result_is_admitted_without_output(self) -> None:
        self.runtime.result_mutation = {
            "verdict": "cancelled",
            "data": {},
            "evidence_refs": [],
        }
        result = json.loads(self.invoke("match", MATCH_PAYLOAD))
        self.assertEqual(result["verdict"], "cancelled")
        self.assertEqual(result["data"], {})
        self.assertEqual(result["evidence_refs"], [])
        self.assertEqual(result["usage"]["model_calls"], 0)
        self.assertEqual(result["effect_receipts"], [])

    def test_valid_typed_input_reaches_canonical_host_with_zero_model_limit(self) -> None:
        result = json.loads(self.invoke("match", MATCH_PAYLOAD))
        self.assertEqual(self.runtime.resolved, ["expert.invoke"])
        self.assertEqual(len(self.runtime.requests), 1)
        request = self.runtime.requests[0]
        self.assertEqual(request["input"], MATCH_PAYLOAD)
        self.assertEqual(request["limits"]["max_model_calls"], 0)
        self.assertEqual(result["usage"]["model_calls"], 0)
        self.assertEqual(result["effect_receipts"], [])


if __name__ == "__main__":
    unittest.main()
