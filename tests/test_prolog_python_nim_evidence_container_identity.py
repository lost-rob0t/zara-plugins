from __future__ import annotations

import unittest

from tests import test_prolog_python_nim_result_snapshot as snapshot


class _TupleEvidenceRuntime(snapshot._Runtime):
    def invoke_capability(self, handle: str, request: dict[str, object]):
        result = super().invoke_capability(handle, request)
        result["evidence_refs"] = tuple(result["evidence_refs"])
        return result


class PrologPythonNimEvidenceContainerIdentityTests(unittest.TestCase):
    def test_non_json_evidence_tuple_fails_closed_before_projection(self) -> None:
        for module, error_type, source in snapshot.CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                runtime = _TupleEvidenceRuntime(module)
                with self.assertRaisesRegex(error_type, "invalid-expert-evidence"):
                    snapshot._invoke(module, runtime, source)
                self.assertEqual(
                    runtime.requests[0]["limits"]["max_model_calls"],
                    0,
                )


if __name__ == "__main__":
    unittest.main()
