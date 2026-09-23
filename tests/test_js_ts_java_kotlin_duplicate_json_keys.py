from __future__ import annotations

import json
import unittest

from tests import test_js_ts_java_kotlin_result_snapshot as snapshot


class _NoDispatchRuntime:
    def resolve_capability(self, capability: str):
        raise AssertionError(
            f"ambiguous JSON must fail before host resolution: {capability}"
        )

    def invoke_capability(self, _handle, _request):
        raise AssertionError("ambiguous JSON must fail before host invocation")


class JsTsJavaKotlinDuplicateJsonKeyFenceTests(unittest.TestCase):
    @staticmethod
    def _invoke_ambiguous(module, error_type, input_json: str) -> None:
        plugin = module.create_plugin()
        plugin.start(_NoDispatchRuntime())
        with unittest.TestCase().assertRaisesRegex(error_type, "ambiguous-input-json"):
            plugin.invoke(
                snapshot.REQUEST_ID,
                snapshot.ACTIVATION_ID,
                snapshot.EXPERT_OPERATION,
                snapshot.EXPECTED_GENERATION,
                snapshot.EXPECTED_GENERATION,
                input_json,
            )

    def test_duplicate_top_level_source_fails_closed_before_dispatch(self) -> None:
        for module, error_type, source in snapshot.CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                input_json = (
                    '{"source":'
                    + json.dumps(source)
                    + ',"source":'
                    + json.dumps(source + " ")
                    + ',"source_generation":"source:generation:1"}'
                )
                self._invoke_ambiguous(module, error_type, input_json)

    def test_duplicate_nested_keys_win_over_schema_errors_before_dispatch(self) -> None:
        for module, error_type, source in snapshot.CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                input_json = (
                    '{"source":'
                    + json.dumps(source)
                    + ',"source_generation":"source:generation:1",'
                    + '"meta":{"path":"safe","path":"other"}}'
                )
                self._invoke_ambiguous(module, error_type, input_json)


if __name__ == "__main__":
    unittest.main()
