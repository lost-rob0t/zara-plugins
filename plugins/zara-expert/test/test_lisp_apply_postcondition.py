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
        self.receipt = {
            "receipt_id": "edit:42",
            "capability": "filesystem_write",
            "source_generation": "project:4",
        }
        self.postcondition = {
            "checker": "sbcl-reader",
            "verified": True,
            "observed_generation": "project:5",
        }

    def test_core_apply_success_requires_and_preserves_fresh_postcondition_evidence(self):
        node, registry, budget = invoke_apply(
            core_result(
                data={
                    "effect_receipt": self.receipt,
                    "postcondition_evidence": self.postcondition,
                },
                evidence_refs=("postcondition:sbcl:project:5",),
                effect_receipts=(self.receipt,),
            )
        )

        self.assertEqual(node.status, "succeeded")
        self.assertEqual(node.data["effect_receipt"], self.receipt)
        self.assertEqual(node.data["postcondition_evidence"], self.postcondition)
        self.assertEqual(node.evidence, ("postcondition:sbcl:project:5",))
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

    def test_core_apply_success_requires_effect_receipt_lineage_match(self):
        mismatched = dict(self.receipt, receipt_id="edit:other")
        with self.assertRaisesRegex(CompositionError, "effect receipt"):
            invoke_apply(
                core_result(
                    data={
                        "effect_receipt": mismatched,
                        "postcondition_evidence": self.postcondition,
                    },
                    evidence_refs=("postcondition:sbcl:project:5",),
                    effect_receipts=(self.receipt,),
                )
            )

    def test_core_apply_success_requires_postcondition_evidence_reference(self):
        with self.assertRaisesRegex(CompositionError, "evidence"):
            invoke_apply(
                core_result(
                    data={
                        "effect_receipt": self.receipt,
                        "postcondition_evidence": self.postcondition,
                    },
                    evidence_refs=(),
                    effect_receipts=(self.receipt,),
                )
            )


if __name__ == "__main__":
    unittest.main()
