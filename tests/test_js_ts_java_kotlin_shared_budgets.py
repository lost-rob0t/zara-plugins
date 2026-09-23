from __future__ import annotations

import json
import unittest

from tests import test_js_ts_java_kotlin_result_snapshot as snapshot


class _NoDispatchRuntime:
    def resolve_capability(self, capability: str):
        raise AssertionError(f"invalid budget must fail before host resolution: {capability}")

    def invoke_capability(self, _handle, _request):
        raise AssertionError("invalid budget must fail before host invocation")


class JsTsJavaKotlinSharedBudgetTests(unittest.TestCase):
    @staticmethod
    def _input(source: str) -> str:
        return json.dumps(
            {
                "source": source,
                "source_generation": "source:generation:1",
            }
        )

    def test_caller_budget_is_preserved_for_canonical_host(self) -> None:
        for module, _error_type, source in snapshot.CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                runtime = snapshot._Runtime(module)
                plugin = module.create_plugin()
                plugin.start(runtime)
                projected = json.loads(
                    plugin.invoke(
                        snapshot.REQUEST_ID,
                        snapshot.ACTIVATION_ID,
                        snapshot.EXPERT_OPERATION,
                        snapshot.EXPECTED_GENERATION,
                        snapshot.EXPECTED_GENERATION,
                        self._input(source),
                        timeout_ms=2500,
                        max_results=8,
                        max_output_bytes=32768,
                    )
                )

                self.assertEqual(
                    runtime.requests[0]["limits"],
                    {
                        "timeout_ms": 2500,
                        "max_results": 8,
                        "max_output_bytes": 32768,
                        "max_model_calls": 0,
                    },
                )
                self.assertEqual(projected["usage"], {"model_calls": 0})
                self.assertEqual(projected["effect_receipts"], [])

    def test_non_integer_and_out_of_range_budgets_fail_before_dispatch(self) -> None:
        cases = (
            ("timeout_ms", 2500.0, "invalid-timeout-ms"),
            ("timeout_ms", True, "invalid-timeout-ms"),
            ("timeout_ms", 0, "invalid-timeout-ms"),
            ("timeout_ms", 3001, "invalid-timeout-ms"),
            ("max_results", 8.0, "invalid-max-results"),
            ("max_results", True, "invalid-max-results"),
            ("max_results", 0, "invalid-max-results"),
            ("max_results", 33, "invalid-max-results"),
            ("max_output_bytes", 32768.0, "invalid-max-output-bytes"),
            ("max_output_bytes", True, "invalid-max-output-bytes"),
            ("max_output_bytes", 0, "invalid-max-output-bytes"),
            ("max_output_bytes", 65537, "invalid-max-output-bytes"),
        )
        for module, error_type, source in snapshot.CASES:
            for field, value, error in cases:
                with self.subTest(expert_id=module.EXPERT_ID, field=field, value=value):
                    plugin = module.create_plugin()
                    plugin.start(_NoDispatchRuntime())
                    kwargs = {field: value}
                    with self.assertRaisesRegex(error_type, error):
                        plugin.invoke(
                            snapshot.REQUEST_ID,
                            snapshot.ACTIVATION_ID,
                            snapshot.EXPERT_OPERATION,
                            snapshot.EXPECTED_GENERATION,
                            snapshot.EXPECTED_GENERATION,
                            self._input(source),
                            **kwargs,
                        )


if __name__ == "__main__":
    unittest.main()
