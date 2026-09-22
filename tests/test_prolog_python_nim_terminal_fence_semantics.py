from __future__ import annotations

import unittest

from tests import test_prolog_python_nim_result_snapshot as snapshot


class _TerminalRuntime(snapshot._Runtime):
    def __init__(self, module, *, error_code: str) -> None:
        super().__init__(module)
        self.error_code = error_code

    def invoke_capability(self, handle: str, request: dict[str, object]):
        result = super().invoke_capability(handle, request)
        result["error_code"] = self.error_code
        result["error_message"] = "terminal fence fired after dispatch"
        return result


class PrologPythonNimTerminalFenceSemanticsTests(unittest.TestCase):
    def test_succeeded_result_cannot_smuggle_cancel_or_stale_error(self) -> None:
        for module, error_type, source in snapshot.CASES:
            for error_code in ("cancelled", "stale_generation"):
                with self.subTest(expert_id=module.EXPERT_ID, error_code=error_code):
                    runtime = _TerminalRuntime(module, error_code=error_code)
                    with self.assertRaisesRegex(error_type, "terminal-fence"):
                        snapshot._invoke(module, runtime, source)
                    self.assertEqual(len(runtime.requests), 1)
                    self.assertEqual(
                        runtime.requests[0]["limits"]["max_model_calls"],
                        0,
                    )


if __name__ == "__main__":
    unittest.main()
