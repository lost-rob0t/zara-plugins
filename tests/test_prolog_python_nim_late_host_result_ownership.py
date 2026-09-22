from __future__ import annotations

import json
import unittest

from tests import test_prolog_python_nim_result_snapshot as snapshot


class _CapturingRuntime(snapshot._Runtime):
    def __init__(self, module) -> None:
        super().__init__(module)
        self.host_result: dict[str, object] | None = None

    def invoke_capability(self, handle: str, request: dict[str, object]):
        result = super().invoke_capability(handle, request)
        self.host_result = result
        return result


class PrologPythonNimLateHostResultOwnershipTests(unittest.TestCase):
    def test_late_host_nested_mutation_cannot_rewrite_projected_result(self) -> None:
        for module, _error_type, source in snapshot.CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                runtime = _CapturingRuntime(module)
                original_validate = module._validate_result
                calls = 0

                def validate_then_mutate_host(result, **kwargs):
                    nonlocal calls
                    calls += 1
                    original_validate(result, **kwargs)
                    if calls == 2:
                        if runtime.host_result is None:
                            raise AssertionError("host result was not captured")
                        runtime.host_result["data"]["result"]["language"] = "late-host-rewrite"  # type: ignore[index]

                module._validate_result = validate_then_mutate_host
                try:
                    encoded = snapshot._invoke(module, runtime, source)
                finally:
                    module._validate_result = original_validate

                projected = json.loads(encoded)
                self.assertGreaterEqual(calls, 3)
                self.assertEqual(
                    projected["data"]["result"]["language"],
                    module.LANGUAGE_BOUNDARIES["language"],
                )
                self.assertEqual(projected["usage"], {"model_calls": 0})
                self.assertEqual(projected["effect_receipts"], [])
                self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)
                self.assertIn(
                    snapshot._expected_provenance_ref(module),
                    projected["evidence_refs"],
                )


if __name__ == "__main__":
    unittest.main()
