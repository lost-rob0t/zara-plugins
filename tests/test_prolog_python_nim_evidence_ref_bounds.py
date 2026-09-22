from __future__ import annotations

import unittest

from tests import test_prolog_python_nim_result_snapshot as snapshot


CASES = snapshot.CASES


class PrologPythonNimEvidenceRefBoundsTests(unittest.TestCase):
    def test_host_evidence_refs_match_canonical_zara_bounds(self) -> None:
        hostile_refs = (
            [""],
            ["x" * 129],
        )

        for module, error_type, source in CASES:
            for evidence_refs in hostile_refs:
                with self.subTest(
                    expert_id=module.EXPERT_ID,
                    evidence_refs=evidence_refs,
                ):
                    runtime = snapshot._Runtime(module, evidence_refs=evidence_refs)
                    with self.assertRaisesRegex(error_type, "invalid-expert-evidence"):
                        snapshot._invoke(module, runtime, source)
                    self.assertEqual(
                        runtime.requests[0]["limits"]["max_model_calls"],
                        0,
                    )


if __name__ == "__main__":
    unittest.main()
