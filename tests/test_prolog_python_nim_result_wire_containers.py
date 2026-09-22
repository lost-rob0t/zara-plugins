from __future__ import annotations

import json
import unittest

from tests import test_prolog_python_nim_result_snapshot as snapshot


class _WireRuntime(snapshot._Runtime):
    def __init__(
        self,
        module,
        *,
        data: dict[str, object],
        effect_receipts: object,
        verdict: str = "succeeded",
    ) -> None:
        super().__init__(module)
        self.data = data
        self.effect_receipts = effect_receipts
        self.verdict = verdict

    def invoke_capability(self, handle: str, request: dict[str, object]):
        result = super().invoke_capability(handle, request)
        result["data"] = self.data
        result["effect_receipts"] = self.effect_receipts
        result["verdict"] = self.verdict
        if self.verdict != "succeeded":
            result["evidence_refs"] = []
            result["error_code"] = "unavailable"
            result["error_message"] = "fixture failure"
        return result


class PrologPythonNimResultWireContainerTests(unittest.TestCase):
    def test_nested_result_arrays_must_be_exact_json_lists(self) -> None:
        for module, error_type, source in snapshot.CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                runtime = _WireRuntime(
                    module,
                    data={
                        "result": {
                            "language": module.LANGUAGE_BOUNDARIES["language"],
                            "host_owned_items": ("one", "two"),
                        }
                    },
                    effect_receipts=[],
                )
                with self.assertRaisesRegex(error_type, "invalid-expert-data-json"):
                    snapshot._invoke(module, runtime, source)

                self.assertEqual(len(runtime.requests), 1)
                self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)

    def test_effect_receipts_must_be_exact_json_list(self) -> None:
        for module, error_type, source in snapshot.CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                runtime = _WireRuntime(
                    module,
                    data={},
                    effect_receipts=(),
                    verdict="failed",
                )
                with self.assertRaisesRegex(
                    error_type,
                    "read-only-effect-proof-missing",
                ):
                    snapshot._invoke(module, runtime, source)

                self.assertEqual(len(runtime.requests), 1)
                self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)

    def test_canonical_json_containers_remain_zero_model_and_read_only(self) -> None:
        for module, _error_type, source in snapshot.CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                runtime = _WireRuntime(
                    module,
                    data={
                        "result": {
                            "language": module.LANGUAGE_BOUNDARIES["language"],
                            "host_owned_items": ["one", "two"],
                        }
                    },
                    effect_receipts=[],
                )
                projected = json.loads(snapshot._invoke(module, runtime, source))

                self.assertEqual(
                    projected["data"]["result"]["host_owned_items"],
                    ["one", "two"],
                )
                self.assertEqual(projected["usage"], {"model_calls": 0})
                self.assertEqual(projected["effect_receipts"], [])
                self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)


if __name__ == "__main__":
    unittest.main()
