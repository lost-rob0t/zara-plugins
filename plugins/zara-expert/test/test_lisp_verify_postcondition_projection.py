import hashlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

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


def core_result(*, data, evidence_refs, status="succeeded"):
    return SimpleNamespace(
        verdict=SimpleNamespace(value=status),
        data=data,
        evidence_refs=evidence_refs,
        usage={"model_calls": 0},
        effect_receipts=(),
    )


def invoke_verify(expert_id, result, *, source_generation="project:4", candidate="(print 1)"):
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
        "repair.verify",
        {
            "arguments": ["(print 1", candidate],
            "source_generation": source_generation,
        },
        budget=budget,
        fence=current_fence(),
    )
    return node, registry, budget


class LispVerifyPostconditionProjectionTests(unittest.TestCase):
    def setUp(self):
        self.expert_id = "zara:expert/common-lisp"
        self.source_generation = "project:4"
        self.candidate = "(print 1)"
        self.candidate_sha256 = hashlib.sha256(self.candidate.encode("utf-8")).hexdigest()
        self.receipt_ref = (
            "zara.verified-outcome/v1:outcome:postcondition/common-lisp-project-4"
        )
        self.postcondition = {
            "receipt_ref": self.receipt_ref,
            "required_postcondition": "sbcl_fresh_reader_and_compile_evidence",
            "source_generation": self.source_generation,
            "candidate_sha256": self.candidate_sha256,
        }

    def successful_result(self, *, data=None, evidence_refs=None):
        resolved_data = (
            {
                "result": {
                    "ok": True,
                    "results": [
                        "verified(false)",
                        "required_postcondition(sbcl_fresh_reader_and_compile_evidence)",
                    ],
                    "trace": ["common-lisp:verify_repair/3"],
                },
                "verified": True,
                "verified_outcome_ref": self.receipt_ref,
                "postcondition_evidence": self.postcondition,
            }
            if data is None
            else data
        )
        resolved_evidence = (
            (self.receipt_ref,) if evidence_refs is None else evidence_refs
        )
        return core_result(data=resolved_data, evidence_refs=resolved_evidence)

    def test_core_verify_success_requires_exact_bound_postcondition_projection(self):
        node, registry, budget = invoke_verify(
            self.expert_id,
            self.successful_result(),
            source_generation=self.source_generation,
            candidate=self.candidate,
        )

        self.assertEqual(node.status, "succeeded")
        self.assertIs(node.data["verified"], True)
        self.assertEqual(node.data["verified_outcome_ref"], self.receipt_ref)
        self.assertEqual(node.data["postcondition_evidence"], self.postcondition)
        self.assertEqual(node.evidence, (self.receipt_ref,))
        self.assertEqual(len(registry.calls), 1)
        self.assertEqual(registry.calls[0]["limits"].max_model_calls, 0)
        self.assertEqual(budget.model_calls_used, 0)

    def test_core_verify_success_rejects_mismatched_candidate_digest(self):
        data = dict(self.successful_result().data)
        data["postcondition_evidence"] = dict(
            self.postcondition,
            candidate_sha256="0" * 64,
        )
        with self.assertRaisesRegex(CompositionError, "candidate digest"):
            invoke_verify(self.expert_id, self.successful_result(data=data))

    def test_core_verify_success_rejects_mismatched_source_generation(self):
        data = dict(self.successful_result().data)
        data["postcondition_evidence"] = dict(
            self.postcondition,
            source_generation="project:stale",
        )
        with self.assertRaisesRegex(CompositionError, "source generation"):
            invoke_verify(self.expert_id, self.successful_result(data=data))

    def test_core_verify_success_rejects_wrong_dialect_postcondition(self):
        data = dict(self.successful_result().data)
        data["postcondition_evidence"] = dict(
            self.postcondition,
            required_postcondition="emacs_fresh_reader_and_byte_compile_evidence",
        )
        with self.assertRaisesRegex(CompositionError, "required postcondition"):
            invoke_verify(self.expert_id, self.successful_result(data=data))

    def test_core_verify_success_requires_receipt_field_and_evidence_to_match(self):
        other_ref = "zara.verified-outcome/v1:outcome:postcondition/other"
        data = dict(self.successful_result().data)
        data["verified_outcome_ref"] = other_ref
        with self.assertRaisesRegex(CompositionError, "receipt"):
            invoke_verify(
                self.expert_id,
                self.successful_result(data=data, evidence_refs=(other_ref,)),
            )

    def test_core_verify_success_requires_receipt_in_projected_evidence(self):
        with self.assertRaisesRegex(CompositionError, "evidence reference"):
            invoke_verify(
                self.expert_id,
                self.successful_result(
                    evidence_refs=(
                        f"evidence:lisp:sha256:{'0' * 64}",
                    )
                ),
            )

    def test_generic_lisp_cannot_claim_dialect_verified_success(self):
        generic_ref = "zara.verified-outcome/v1:outcome:postcondition/generic"
        data = {
            "result": {
                "ok": True,
                "results": ["verified(true)"],
                "trace": ["lisp:verify_repair/3"],
            },
            "verified": True,
            "verified_outcome_ref": generic_ref,
            "postcondition_evidence": {
                "receipt_ref": generic_ref,
                "required_postcondition": "sbcl_fresh_reader_and_compile_evidence",
                "source_generation": self.source_generation,
                "candidate_sha256": self.candidate_sha256,
            },
        }
        with self.assertRaisesRegex(CompositionError, "generic Lisp"):
            invoke_verify(
                "zara:expert/lisp",
                core_result(data=data, evidence_refs=(generic_ref,)),
            )


if __name__ == "__main__":
    unittest.main()
