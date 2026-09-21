import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.lisp_family import make_lisp_expert_handler


POSTCONDITIONS = {
    "zara:expert/common-lisp": "sbcl_fresh_reader_and_compile_evidence",
    "zara:expert/emacs-lisp": "emacs_fresh_reader_and_byte_compile_evidence",
}


class PendingVerificationHost:
    def query(self, namespace, predicate, arguments):
        if predicate != "verify_repair":
            raise AssertionError(f"unexpected predicate: {predicate}")
        expert_id = f"zara:expert/{namespace}"
        postcondition = POSTCONDITIONS[expert_id]
        return {
            "ok": True,
            "results": [
                f"repair_verification(expert('{expert_id}'),verified(false),"
                f"required_postcondition({postcondition}))"
            ],
            "trace": ["registered-predicate"],
        }


class ComparisonMasqueradingString(str):
    """String subclass that lies about equality at a trust boundary."""

    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False


class ReceiptResolver:
    def __init__(self, receipt):
        self.receipt = receipt

    def __call__(self, **query):
        return self.receipt


class LispVerifiedOutcomeIdentityTypeTests(unittest.TestCase):
    candidate = "(defun demo (x) (list x))"
    generation = "buffer:8"

    @classmethod
    def _valid_receipt(cls, expert_id, postcondition):
        return {
            "receipt_ref": "zara.verified-outcome/v1:outcome:postcondition/lisp-binding-type-test",
            "expert_id": expert_id,
            "source_generation": cls.generation,
            "candidate_sha256": hashlib.sha256(cls.candidate.encode("utf-8")).hexdigest(),
            "required_postcondition": postcondition,
            "verified": True,
            "fresh": True,
        }

    def _verify(self, expert_id, receipt):
        return make_lisp_expert_handler(
            PendingVerificationHost(),
            expert_id,
            verified_outcome_resolver=ReceiptResolver(receipt),
        )(
            expert_operation="repair.verify",
            arguments=["(defun demo (x) (list x", self.candidate],
            source_generation=self.generation,
        )

    def test_receipt_binding_fields_require_builtin_strings(self):
        for expert_id, postcondition in POSTCONDITIONS.items():
            mismatches = {
                "expert_id": "zara:expert/emacs-lisp"
                if expert_id == "zara:expert/common-lisp"
                else "zara:expert/common-lisp",
                "source_generation": "buffer:stale",
                "candidate_sha256": "0" * 64,
                "required_postcondition": "wrong_postcondition",
            }
            for field, mismatch in mismatches.items():
                with self.subTest(expert_id=expert_id, field=field):
                    receipt = self._valid_receipt(expert_id, postcondition)
                    receipt[field] = ComparisonMasqueradingString(mismatch)
                    outcome = self._verify(expert_id, receipt)
                    self.assertEqual(outcome["verdict"], "blocked")
                    self.assertEqual(outcome["usage"], {"model_calls": 0})
                    self.assertEqual(outcome["effect_receipts"], [])
                    self.assertNotIn("verified_outcome_ref", outcome["data"])


if __name__ == "__main__":
    unittest.main()
