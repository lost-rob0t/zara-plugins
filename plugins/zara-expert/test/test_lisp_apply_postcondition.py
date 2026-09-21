import hashlib
from types import SimpleNamespace
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert import CoreLispFamilyCompositionInvoker
from zara_expert.composition import (
    CompositionError,
    InvocationFence,
    MetaExpertComposer,
    SharedSymbolicBudget,
)


class RecordingCoreRegistry:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def invoke(self, handle, operation, payload, *, limits):
        self.calls.append(
            {
                "handle": handle,
                "operation": operation,
                "payload": dict(payload),
                "limits": limits,
            }
        )
        return self.result


class CoreLimits:
    def __init__(self, *, max_model_calls):
        self.max_model_calls = max_model_calls


def current_fence():
    return InvocationFence(
        workspace_id="project",
        workspace_generation=4,
        is_cancelled=lambda: False,
        is_current_generation=lambda workspace, generation: (
            workspace == "project" and generation == 4
        ),
    )


def core_result(*, data, evidence_refs, effect_receipts):
    return SimpleNamespace(
        verdict=SimpleNamespace(value="succeeded"),
        data=data,
        evidence_refs=evidence_refs,
        usage={"model_calls": 0},
        effect_receipts=effect_receipts,
    )


def invoke_apply(result):
    expert_id = "zara:expert/common-lisp"
    handle = SimpleNamespace(expert_id=expert_id, workspace="project")
    registry = RecordingCoreRegistry(result)
    invoker = CoreLispFamilyCompositionInvoker(
        registry,
        activation_for=lambda _expert_id, _fence: handle,
        limits_factory=CoreLimits,
    )
    budget = SharedSymbolicBudget(max_invocations=1, max_model_calls=0)
    node = MetaExpertComposer(invoker).invoke(
        expert_id,
        "repair.apply",
        {
            "repair": {"replacement": "(print 1)"},
            "expected_preimage": "(print 1",
            "source_generation": "project:4",
        },
        budget=budget,
        fence=current_fence(),
    )
    return node, registry, budget


class LispApplyPostconditionTests(unittest.TestCase):
    def setUp(self):
        self.replacement = "(print 1)"
        self.candidate_sha256 = hashlib.sha256(self.replacement.encode("utf-8")).hexdigest()
        self.postcondition_ref = (
            "zara.verified-outcome/v1:outcome:postcondition/common-lisp-project-5"
        )
        self.receipt = {
            "receipt_id": "edit:42",
            "capability": "filesystem_write",
            "source_generation": "project:4",
        }
        self.postcondition = {
            "checker": "sbcl-reader",
            "expert_id": "zara:expert/common-lisp",
            "verified": True,
            "fresh": True,
            "source_generation": "project:4",
            "observed_generation": "project:5",
            "candidate_sha256": self.candidate_sha256,
            "required_postcondition": "sbcl_fresh_reader_and_compile_evidence",
            "receipt_ref": self.postcondition_ref,
        }

    def successful_result(self, *, postcondition=None, evidence_refs=None):
        resolved_postcondition = self.postcondition if postcondition is None else postcondition
        resolved_evidence = (
            (self.postcondition_ref,) if evidence_refs is None else evidence_refs
        )
        return core_result(
            data={
                "effect_receipt": self.receipt,
                "postcondition_evidence": resolved_postcondition,
            },
            evidence_refs=resolved_evidence,
            effect_receipts=(self.receipt,),
        )

    def test_core_apply_success_requires_and_preserves_fresh_postcondition_evidence(self):
        node, registry, budget = invoke_apply(self.successful_result())

        self.assertEqual(node.status, "succeeded")
        self.assertEqual(node.data["effect_receipt"], self.receipt)
        self.assertEqual(node.data["postcondition_evidence"], self.postcondition)
        self.assertEqual(node.evidence, (self.postcondition_ref,))
        self.assertEqual(len(registry.calls), 1)
        self.assertEqual(registry.calls[0]["operation"], "repair.apply")
        self.assertEqual(registry.calls[0]["limits"].max_model_calls, 0)
        self.assertEqual(budget.model_calls_used, 0)

    def test_core_apply_success_without_postcondition_fails_closed(self):
        with self.assertRaisesRegex(CompositionError, "postcondition"):
            invoke_apply(
                core_result(
                    data={"effect_receipt": self.receipt},
                    evidence_refs=("effect:edit:42",),
                    effect_receipts=(self.receipt,),
                )
            )

    def test_core_apply_success_rejects_explicitly_unverified_postcondition(self):
        postcondition = dict(self.postcondition, verified=False)
        with self.assertRaisesRegex(CompositionError, "verified"):
            invoke_apply(self.successful_result(postcondition=postcondition))

    def test_core_apply_success_rejects_truthy_non_boolean_verification(self):
        postcondition = dict(self.postcondition, verified=1)
        with self.assertRaisesRegex(CompositionError, "verified"):
            invoke_apply(self.successful_result(postcondition=postcondition))

    def test_core_apply_success_requires_literal_fresh_postcondition(self):
        for fresh in (False, 1, "true", None):
            with self.subTest(fresh=fresh):
                postcondition = dict(self.postcondition, fresh=fresh)
                with self.assertRaisesRegex(CompositionError, "fresh"):
                    invoke_apply(self.successful_result(postcondition=postcondition))

    def test_core_apply_success_requires_fresh_observed_generation(self):
        postcondition = dict(self.postcondition, observed_generation="project:4")
        with self.assertRaisesRegex(CompositionError, "fresh"):
            invoke_apply(self.successful_result(postcondition=postcondition))

    def test_core_apply_success_requires_request_receipt_generation_match(self):
        receipt = dict(self.receipt, source_generation="project:stale")
        with self.assertRaisesRegex(CompositionError, "source generation"):
            invoke_apply(
                core_result(
                    data={
                        "effect_receipt": receipt,
                        "postcondition_evidence": self.postcondition,
                    },
                    evidence_refs=(self.postcondition_ref,),
                    effect_receipts=(receipt,),
                )
            )

    def test_core_apply_success_requires_effect_receipt_lineage_match(self):
        mismatched = dict(self.receipt, receipt_id="edit:other")
        with self.assertRaisesRegex(CompositionError, "effect receipt"):
            invoke_apply(
                core_result(
                    data={
                        "effect_receipt": mismatched,
                        "postcondition_evidence": self.postcondition,
                    },
                    evidence_refs=(self.postcondition_ref,),
                    effect_receipts=(self.receipt,),
                )
            )

    def test_core_apply_success_requires_postcondition_evidence_reference(self):
        with self.assertRaisesRegex(CompositionError, "evidence"):
            invoke_apply(self.successful_result(evidence_refs=()))

    def test_core_apply_success_requires_dialect_postcondition_contract(self):
        wrong = dict(
            self.postcondition,
            required_postcondition="emacs_fresh_reader_and_byte_compile_evidence",
        )
        with self.assertRaisesRegex(CompositionError, "required postcondition"):
            invoke_apply(self.successful_result(postcondition=wrong))

    def test_core_apply_success_requires_postcondition_expert_identity(self):
        wrong = dict(self.postcondition, expert_id="zara:expert/emacs-lisp")
        with self.assertRaisesRegex(CompositionError, "expert identity"):
            invoke_apply(self.successful_result(postcondition=wrong))

    def test_core_apply_success_requires_postcondition_source_generation(self):
        wrong = dict(self.postcondition, source_generation="project:stale")
        with self.assertRaisesRegex(CompositionError, "source generation"):
            invoke_apply(self.successful_result(postcondition=wrong))

    def test_core_apply_success_binds_postcondition_to_replacement_digest(self):
        wrong = dict(self.postcondition, candidate_sha256="0" * 64)
        with self.assertRaisesRegex(CompositionError, "candidate digest"):
            invoke_apply(self.successful_result(postcondition=wrong))

    def test_core_apply_success_requires_canonical_verified_outcome_reference(self):
        wrong = dict(self.postcondition, receipt_ref="postcondition:sbcl:project:5")
        with self.assertRaisesRegex(CompositionError, "verified-outcome"):
            invoke_apply(
                self.successful_result(
                    postcondition=wrong,
                    evidence_refs=("postcondition:sbcl:project:5",),
                )
            )

    def test_core_apply_success_requires_receipt_reference_in_projected_evidence(self):
        with self.assertRaisesRegex(CompositionError, "evidence reference"):
            invoke_apply(
                self.successful_result(
                    evidence_refs=("zara.verified-outcome/v1:outcome:postcondition/other",),
                )
            )


if __name__ == "__main__":
    unittest.main()
