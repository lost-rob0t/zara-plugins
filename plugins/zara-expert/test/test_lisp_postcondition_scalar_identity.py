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


class EqualityForgingString(str):
    """A string subclass that can make a mismatched binding compare equal."""

    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False


class FreshnessForgingString(str):
    """A stale generation that lies about equality to bypass freshness checks."""

    def __eq__(self, other):
        return False

    def __ne__(self, other):
        return True


def current_fence():
    return InvocationFence(
        workspace_id="project",
        workspace_generation=4,
        is_cancelled=lambda: False,
        is_current_generation=lambda workspace, generation: (
            workspace == "project" and generation == 4
        ),
    )


def core_result(*, data, evidence_refs, effect_receipts=()):
    return SimpleNamespace(
        verdict=SimpleNamespace(value="succeeded"),
        data=data,
        evidence_refs=evidence_refs,
        usage={"model_calls": 0},
        effect_receipts=effect_receipts,
    )


def invoke(expert_id, operation, input_data, result):
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
        operation,
        input_data,
        budget=budget,
        fence=current_fence(),
    )
    return node, registry, budget


_DIALECTS = (
    (
        "zara:expert/common-lisp",
        "sbcl_fresh_reader_and_compile_evidence",
        "common-lisp-project-5",
        "common-lisp:verify_repair/3",
    ),
    (
        "zara:expert/emacs-lisp",
        "emacs_fresh_reader_and_byte_compile_evidence",
        "emacs-lisp-project-5",
        "emacs-lisp:verify_repair/3",
    ),
)


class LispPostconditionScalarIdentityTests(unittest.TestCase):
    def setUp(self):
        self.source_generation = "project:4"
        self.original = "(print 1"
        self.candidate = "(print 1)"
        self.candidate_sha256 = hashlib.sha256(
            self.candidate.encode("utf-8")
        ).hexdigest()

    def test_verify_rejects_string_subclass_that_forges_candidate_binding(self):
        for expert_id, required_postcondition, suffix, trace in _DIALECTS:
            with self.subTest(expert_id=expert_id):
                receipt_ref = (
                    "zara.verified-outcome/v1:outcome:postcondition/" + suffix
                )
                postcondition = {
                    "receipt_ref": receipt_ref,
                    "required_postcondition": required_postcondition,
                    "source_generation": self.source_generation,
                    "candidate_sha256": EqualityForgingString("0" * 64),
                }
                result = core_result(
                    data={
                        "result": {
                            "ok": True,
                            "results": [
                                "verified(false)",
                                f"required_postcondition({required_postcondition})",
                            ],
                            "trace": [trace],
                        },
                        "verified": True,
                        "verified_outcome_ref": receipt_ref,
                        "postcondition_evidence": postcondition,
                    },
                    evidence_refs=(receipt_ref,),
                )

                with self.assertRaisesRegex(
                    CompositionError,
                    "postcondition evidence candidate_sha256 must be a built-in string",
                ):
                    invoke(
                        expert_id,
                        "repair.verify",
                        {
                            "arguments": [self.original, self.candidate],
                            "source_generation": self.source_generation,
                        },
                        result,
                    )

    def test_apply_rejects_string_subclass_that_forges_fresh_generation(self):
        for expert_id, required_postcondition, suffix, _trace in _DIALECTS:
            with self.subTest(expert_id=expert_id):
                receipt_ref = (
                    "zara.verified-outcome/v1:outcome:postcondition/" + suffix
                )
                effect_receipt = {
                    "receipt_id": "edit:42",
                    "capability": "filesystem_write",
                    "source_generation": self.source_generation,
                }
                postcondition = {
                    "checker": "canonical-dialect-verifier",
                    "expert_id": expert_id,
                    "verified": True,
                    "fresh": True,
                    "source_generation": self.source_generation,
                    # Textually stale, but equality is forged so the old
                    # freshness comparison would treat it as a new generation.
                    "observed_generation": FreshnessForgingString(
                        self.source_generation
                    ),
                    "candidate_sha256": self.candidate_sha256,
                    "required_postcondition": required_postcondition,
                    "receipt_ref": receipt_ref,
                }
                result = core_result(
                    data={
                        "effect_receipt": effect_receipt,
                        "postcondition_evidence": postcondition,
                    },
                    evidence_refs=(receipt_ref,),
                    effect_receipts=(effect_receipt,),
                )

                with self.assertRaisesRegex(
                    CompositionError,
                    "postcondition evidence observed_generation must be a built-in string",
                ):
                    invoke(
                        expert_id,
                        "repair.apply",
                        {
                            "repair": {"replacement": self.candidate},
                            "expected_preimage": self.original,
                            "source_generation": self.source_generation,
                        },
                        result,
                    )


if __name__ == "__main__":
    unittest.main()
