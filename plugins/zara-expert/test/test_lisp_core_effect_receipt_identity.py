import sys
import unittest
from collections import UserDict
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert import CoreLispFamilyCompositionInvoker
from zara_expert.composition import CompositionError, InvocationFence, SharedSymbolicBudget


LISP_EXPERTS = (
    "zara:expert/lisp",
    "zara:expert/common-lisp",
    "zara:expert/emacs-lisp",
)
DIALECT_REPAIR_EXPERTS = (
    "zara:expert/common-lisp",
    "zara:expert/emacs-lisp",
)


class ReceiptTuple(tuple):
    pass


class CoreLimits:
    def __init__(self, *, max_model_calls):
        self.max_model_calls = max_model_calls


class RecordingRegistry:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def invoke(self, handle, operation, payload, *, limits):
        self.calls.append((handle, operation, payload, limits.max_model_calls))
        return self.outcome


def current_fence():
    return InvocationFence(
        workspace_id="project",
        workspace_generation=8,
        is_cancelled=lambda: False,
        is_current_generation=lambda workspace, generation: (
            workspace == "project" and generation == 8
        ),
    )


def handle_for(expert_id):
    return SimpleNamespace(expert_id=expert_id, workspace="project")


def core_outcome(*, data, evidence_refs=("ev:core:lisp",), effect_receipts=()):
    return SimpleNamespace(
        verdict="succeeded",
        data=data,
        evidence_refs=evidence_refs,
        effect_receipts=effect_receipts,
        usage={"model_calls": 0},
    )


class LispCoreEffectReceiptIdentityTests(unittest.TestCase):
    def _invoke(self, expert_id, operation, payload, outcome):
        registry = RecordingRegistry(outcome)
        invoker = CoreLispFamilyCompositionInvoker(
            registry,
            activation_for=lambda requested_expert_id, fence: handle_for(
                requested_expert_id
            ),
            limits_factory=CoreLimits,
        )
        budget = SharedSymbolicBudget(max_invocations=1, max_model_calls=0)

        with self.assertRaisesRegex(CompositionError, "built-in"):
            invoker(
                expert_id,
                operation,
                payload,
                budget=budget,
                fence=current_fence(),
                parent_path=(),
            )

        self.assertEqual(len(registry.calls), 1)
        self.assertEqual(registry.calls[0][3], 0)
        self.assertEqual(budget.model_calls_used, 0)

    def test_rejects_custom_effect_receipt_sequence_for_all_lisp_experts(self):
        for expert_id in LISP_EXPERTS:
            with self.subTest(expert_id=expert_id):
                self._invoke(
                    expert_id,
                    "structural.check",
                    {"arguments": ["(list 1 2)"]},
                    core_outcome(
                        data={"result": {"ok": True}},
                        effect_receipts=ReceiptTuple(),
                    ),
                )

    def test_rejects_custom_effect_receipt_mapping_before_apply_projection(self):
        required_postconditions = {
            "zara:expert/common-lisp": "sbcl_fresh_reader_and_compile_evidence",
            "zara:expert/emacs-lisp": "emacs_fresh_reader_and_byte_compile_evidence",
        }
        for expert_id in DIALECT_REPAIR_EXPERTS:
            with self.subTest(expert_id=expert_id):
                receipt = {
                    "receipt_id": "edit:42",
                    "capability": "filesystem_write",
                    "source_generation": "project:8",
                }
                postcondition_ref = (
                    "zara.verified-outcome/v1:outcome:postcondition/project-9"
                )
                postcondition = {
                    "checker": "reader",
                    "expert_id": expert_id,
                    "verified": True,
                    "fresh": True,
                    "source_generation": "project:8",
                    "observed_generation": "project:9",
                    "candidate_sha256": "0" * 64,
                    "required_postcondition": required_postconditions[expert_id],
                    "receipt_ref": postcondition_ref,
                }
                self._invoke(
                    expert_id,
                    "repair.apply",
                    {
                        "repair": {"replacement": "(print 1)"},
                        "expected_preimage": "(print 1",
                        "source_generation": "project:8",
                    },
                    core_outcome(
                        data={
                            "effect_receipt": receipt,
                            "postcondition_evidence": postcondition,
                        },
                        evidence_refs=(postcondition_ref,),
                        effect_receipts=(UserDict(receipt),),
                    ),
                )


if __name__ == "__main__":
    unittest.main()
