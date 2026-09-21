import hashlib
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


class _ReceiptResolver:
    def __init__(self, receipt):
        self.receipt = receipt
        self.requests = []

    def __call__(self, **request):
        self.requests.append(dict(request))
        return dict(self.receipt)


def _receipt(
    *,
    expert_id,
    source_generation,
    candidate_source,
    required_postcondition,
    suffix="tool-run-verify",
):
    return {
        "receipt_ref": f"zara.verified-outcome/v1:outcome:postcondition/{suffix}",
        "expert_id": expert_id,
        "source_generation": source_generation,
        "candidate_sha256": hashlib.sha256(candidate_source.encode("utf-8")).hexdigest(),
        "required_postcondition": required_postcondition,
        "verified": True,
        "fresh": True,
    }


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

    def test_nix_and_bash_accept_only_fresh_core_bound_postcondition_receipts(self):
        host = _NegativeVerificationHost()
        cases = (
            ("zara:expert/nix", "{ x = 1; }", "{ x = 2; }", "parse_then_eval_or_check"),
            ("zara:expert/bash", "printf '%s\\n' ok", "printf '%s\\n' fixed", "parse_and_bash_n"),
        )
        for expert_id, original, candidate, required in cases:
            with self.subTest(expert_id=expert_id):
                receipt = _receipt(
                    expert_id=expert_id,
                    source_generation="generation-verify",
                    candidate_source=candidate,
                    required_postcondition=required,
                    suffix=f"{expert_id.rsplit('/', 1)[-1]}-verify",
                )
                resolver = _ReceiptResolver(receipt)
                outcome = make_language_expert_handler(
                    host,
                    expert_id,
                    verified_outcome_resolver=resolver,
                )(
                    expert_operation="repair.verify",
                    original_source=original,
                    candidate_source=candidate,
                    source_generation="generation-verify",
                )

                self.assertEqual(outcome["verdict"], "succeeded")
                self.assertEqual(outcome["usage"], {"model_calls": 0})
                self.assertEqual(outcome["effect_receipts"], [])
                self.assertEqual(outcome["data"]["verified"], True)
                self.assertEqual(
                    outcome["data"]["verified_outcome_ref"],
                    receipt["receipt_ref"],
                )
                self.assertIn(receipt["receipt_ref"], outcome["evidence_refs"])
                self.assertEqual(len(resolver.requests), 1)
                self.assertEqual(
                    resolver.requests[0],
                    {
                        "expert_id": expert_id,
                        "source_generation": "generation-verify",
                        "candidate_sha256": receipt["candidate_sha256"],
                        "required_postcondition": required,
                    },
                )

    def test_mismatched_or_stale_postcondition_receipt_stays_blocked(self):
        host = _NegativeVerificationHost()
        candidate = "{ x = 2; }"
        base = _receipt(
            expert_id="zara:expert/nix",
            source_generation="generation-verify",
            candidate_source=candidate,
            required_postcondition="parse_then_eval_or_check",
        )
        mutations = (
            ("expert_id", "zara:expert/bash"),
            ("source_generation", "generation-stale"),
            ("candidate_sha256", "0" * 64),
            ("required_postcondition", "parse_and_bash_n"),
            ("verified", False),
            ("fresh", False),
            ("receipt_ref", "zara.verified-outcome/v1:effect:not-a-postcondition"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                receipt = dict(base)
                receipt[field] = value
                outcome = make_language_expert_handler(
                    host,
                    "zara:expert/nix",
                    verified_outcome_resolver=_ReceiptResolver(receipt),
                )(
                    expert_operation="repair.verify",
                    original_source="{ x = 1; }",
                    candidate_source=candidate,
                    source_generation="generation-verify",
                )
                self.assertEqual(outcome["verdict"], "blocked")
                self.assertEqual(outcome["usage"], {"model_calls": 0})
                self.assertEqual(outcome["effect_receipts"], [])
                self.assertNotIn(base["receipt_ref"], outcome["evidence_refs"])


if __name__ == "__main__":
    unittest.main()
