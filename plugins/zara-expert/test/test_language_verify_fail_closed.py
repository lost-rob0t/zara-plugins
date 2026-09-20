import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.language_handler import make_language_expert_handler


class _NegativeVerificationHost:
    """Minimal registered-predicate stand-in for the canonical negative verifier."""

    def query(self, namespace, predicate, arguments):
        if predicate != "language_repair_verify":
            raise AssertionError(f"unexpected predicate: {predicate}")
        if namespace == "nix-expert":
            verification = "parse_then_eval_or_check"
        elif namespace == "bash-expert":
            verification = "parse_and_bash_n"
        else:
            raise AssertionError(f"unexpected namespace: {namespace}")
        return {
            "ok": True,
            "results": [
                "language_repair_verification("
                f"expert('zara:expert/{namespace.removesuffix('-expert')}'),"
                "verified(false),"
                f"reason(fresh_postcondition_required({verification})),"
                f"required_postcondition({verification}),"
                "generation('generation-verify'))"
            ],
            "trace": [],
        }

    def explain(self, namespace, predicate, arguments):
        raise AssertionError("repair.verify must use the registered query boundary")


class LanguageRepairVerifyFailClosedTests(unittest.TestCase):
    def test_nix_and_bash_negative_symbolic_verification_cannot_report_success(self):
        host = _NegativeVerificationHost()
        cases = (
            ("zara:expert/nix", "{ x = 1; }", "{ x = 2; }", "parse_then_eval_or_check"),
            ("zara:expert/bash", "printf '%s\\n' ok", "printf '%s\\n' fixed", "parse_and_bash_n"),
        )
        for expert_id, original, candidate, required in cases:
            with self.subTest(expert_id=expert_id):
                outcome = make_language_expert_handler(host, expert_id)(
                    expert_operation="repair.verify",
                    original_source=original,
                    candidate_source=candidate,
                    source_generation="generation-verify",
                )
                self.assertEqual(outcome["verdict"], "blocked")
                self.assertEqual(outcome["usage"], {"model_calls": 0})
                self.assertEqual(outcome["effect_receipts"], [])
                evidence = "\n".join(outcome["data"]["result"]["evidence"])
                self.assertIn("verified(false)", evidence)
                self.assertIn(f"fresh_postcondition_required({required})", evidence)


if __name__ == "__main__":
    unittest.main()
