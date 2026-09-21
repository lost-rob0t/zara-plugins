import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertHost
from zara_expert.lisp_family import (
    descriptors,
    lisp_family_specs,
    make_lisp_expert_handler,
    register_lisp_family,
    registered_predicates,
)


POSTCONDITIONS = {
    "common-lisp": "sbcl_fresh_reader_and_compile_evidence",
    "emacs-lisp": "emacs_fresh_reader_and_byte_compile_evidence",
}


class PendingDialectVerificationBackend:
    def __init__(self):
        self.calls = []

    def run(self, request):
        self.calls.append(dict(request))
        namespace = request["capability"].namespace
        required = POSTCONDITIONS.get(namespace, "fresh_dialect_reader_postcondition")
        expert_id = f"zara:expert/{namespace}"
        return {
            "ok": True,
            "results": [
                f"repair_verification(expert('{expert_id}'),verified(false),"
                f"required_postcondition({required}))"
            ],
            "trace": ["registered-predicate"],
        }


class ReceiptResolver:
    def __init__(self, receipt=None, *, raises=False):
        self.receipt = receipt
        self.raises = raises
        self.calls = []

    def __call__(self, **query):
        self.calls.append(dict(query))
        if self.raises:
            raise RuntimeError("resolver unavailable")
        return self.receipt


class LispVerifiedOutcomeReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.backend = PendingDialectVerificationBackend()
        self.host = ExpertHost(self.backend, state_root=self.root / "state")
        exports = [
            *(f"{predicate}/{arity}" for predicate, arity in registered_predicates().items()),
            "provider_policy/1",
            "max_model_calls/1",
            "model_calls/1",
        ]
        sources = {}
        for spec in lisp_family_specs():
            path = self.root / f"{spec.key}.pl"
            module_name = f"fixture_{spec.key.replace('-', '_')}"
            path.write_text(
                f":- module({module_name}, [{', '.join(exports)}]).\n"
                "provider_policy(disabled).\n"
                "max_model_calls(0).\n"
                "model_calls(0).\n",
                encoding="utf-8",
            )
            sources[spec.key] = [path]
        register_lisp_family(self.host, sources)

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def _receipt(expert_id, generation, candidate, postcondition, **overrides):
        receipt = {
            "receipt_ref": "zara.verified-outcome/v1:outcome:postcondition/lisp-repair-7",
            "expert_id": expert_id,
            "source_generation": generation,
            "candidate_sha256": hashlib.sha256(candidate.encode("utf-8")).hexdigest(),
            "required_postcondition": postcondition,
            "verified": True,
            "fresh": True,
        }
        receipt.update(overrides)
        return receipt

    def _verify(self, expert_id, resolver, *, generation="buffer:8"):
        return make_lisp_expert_handler(
            self.host,
            expert_id,
            verified_outcome_resolver=resolver,
        )(
            expert_operation="repair.verify",
            arguments=["(defun demo (x) (list x", "(defun demo (x) (list x))"],
            source_generation=generation,
        )

    def test_exact_common_lisp_and_emacs_lisp_receipts_promote_blocked_verification(self):
        candidate = "(defun demo (x) (list x))"
        for key, postcondition in POSTCONDITIONS.items():
            expert_id = f"zara:expert/{key}"
            with self.subTest(expert=expert_id):
                resolver = ReceiptResolver(
                    self._receipt(expert_id, "buffer:8", candidate, postcondition)
                )
                outcome = self._verify(expert_id, resolver)
                self.assertEqual(outcome["verdict"], "succeeded")
                self.assertEqual(outcome["usage"], {"model_calls": 0})
                self.assertEqual(outcome["effect_receipts"], [])
                self.assertIs(outcome["data"]["verified"], True)
                self.assertEqual(
                    outcome["data"]["verified_outcome_ref"],
                    "zara.verified-outcome/v1:outcome:postcondition/lisp-repair-7",
                )
                self.assertIn(outcome["data"]["verified_outcome_ref"], outcome["evidence_refs"])
                self.assertEqual(
                    resolver.calls,
                    [
                        {
                            "expert_id": expert_id,
                            "source_generation": "buffer:8",
                            "candidate_sha256": hashlib.sha256(candidate.encode("utf-8")).hexdigest(),
                            "required_postcondition": postcondition,
                        }
                    ],
                )

    def test_missing_stale_malformed_or_mismatched_receipts_fail_closed(self):
        expert_id = "zara:expert/common-lisp"
        candidate = "(defun demo (x) (list x))"
        postcondition = POSTCONDITIONS["common-lisp"]
        valid = self._receipt(expert_id, "buffer:8", candidate, postcondition)
        cases = (
            None,
            {**valid, "expert_id": "zara:expert/emacs-lisp"},
            {**valid, "source_generation": "buffer:7"},
            {**valid, "candidate_sha256": "0" * 64},
            {**valid, "required_postcondition": "wrong_postcondition"},
            {**valid, "verified": False},
            {**valid, "verified": 1},
            {**valid, "fresh": False},
            {**valid, "fresh": 1},
            {**valid, "receipt_ref": "zara.verified-outcome/v1:effect:lisp-repair-7"},
            {**valid, "receipt_ref": "receipt:not-canonical"},
        )
        for receipt in cases:
            with self.subTest(receipt=receipt):
                outcome = self._verify(expert_id, ReceiptResolver(receipt))
                self.assertEqual(outcome["verdict"], "blocked")
                self.assertEqual(outcome["usage"], {"model_calls": 0})
                self.assertEqual(outcome["effect_receipts"], [])
                self.assertNotIn("verified_outcome_ref", outcome["data"])

        resolver_error = self._verify(expert_id, ReceiptResolver(raises=True))
        self.assertEqual(resolver_error["verdict"], "blocked")

    def test_generic_lisp_cannot_claim_dialect_postcondition_receipt(self):
        candidate = "(list value)"
        resolver = ReceiptResolver(
            self._receipt(
                "zara:expert/lisp",
                "buffer:8",
                candidate,
                "fresh_dialect_reader_postcondition",
            )
        )
        outcome = make_lisp_expert_handler(
            self.host,
            "zara:expert/lisp",
            verified_outcome_resolver=resolver,
        )(
            expert_operation="repair.verify",
            arguments=["(list value", candidate],
            source_generation="buffer:8",
        )
        self.assertEqual(outcome["verdict"], "blocked")
        self.assertEqual(resolver.calls, [])
        self.assertEqual(outcome["usage"], {"model_calls": 0})

    def test_verify_descriptor_exposes_generation_but_never_receipt_authority(self):
        for item in descriptors():
            verify = next(
                operation for operation in item["operations"]
                if operation["operation_id"] == "repair.verify"
            )
            names = {field["name"] for field in verify["input_schema"]["fields"]}
            self.assertEqual(names, {"arguments", "source_generation"})
            self.assertNotIn("verified_outcome", names)
            self.assertNotIn("receipt", names)


if __name__ == "__main__":
    unittest.main()
