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


_DIALECTS = (
    (
        "zara:expert/common-lisp",
        "sbcl_fresh_reader_and_compile_evidence",
        "common-lisp-project-5",
    ),
    (
        "zara:expert/emacs-lisp",
        "emacs_fresh_reader_and_byte_compile_evidence",
        "emacs-lisp-project-5",
    ),
)


class AuthorityForgingKey:
    """A non-string dict key that aliases one canonical authority field."""

    def __init__(self, target):
        self.target = target

    def __hash__(self):
        return hash(self.target)

    def __eq__(self, other):
        return other == self.target

    def __ne__(self, other):
        return not self.__eq__(other)


class RecordingCoreRegistry:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def invoke(self, handle, operation, payload, *, limits):
        self.calls.append((handle, operation, dict(payload), limits.max_model_calls))
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


def canonical_postcondition(expert_id, required_postcondition, suffix):
    replacement = "(print 1)"
    return {
        "checker": "canonical-dialect-verifier",
        "expert_id": expert_id,
        "verified": True,
        "fresh": True,
        "source_generation": "project:4",
        "observed_generation": "project:5",
        "candidate_sha256": hashlib.sha256(replacement.encode("utf-8")).hexdigest(),
        "required_postcondition": required_postcondition,
        "receipt_ref": "zara.verified-outcome/v1:outcome:postcondition/" + suffix,
    }


def successful_apply_result(*, receipt, postcondition):
    return SimpleNamespace(
        verdict=SimpleNamespace(value="succeeded"),
        data={
            "effect_receipt": receipt,
            "postcondition_evidence": postcondition,
        },
        evidence_refs=(postcondition["receipt_ref"],),
        usage={"model_calls": 0},
        effect_receipts=(receipt,),
    )


def invoke_apply(expert_id, result):
    registry = RecordingCoreRegistry(result)
    invoker = CoreLispFamilyCompositionInvoker(
        registry,
        activation_for=lambda requested_expert_id, _fence: SimpleNamespace(
            expert_id=requested_expert_id,
            workspace="project",
        ),
        limits_factory=CoreLimits,
    )
    budget = SharedSymbolicBudget(max_invocations=1, max_model_calls=0)
    with unittest.TestCase().assertRaisesRegex(CompositionError, "built-in strings"):
        MetaExpertComposer(invoker).invoke(
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
    return registry, budget


class LispAuthorityKeyIdentityTests(unittest.TestCase):
    def test_rejects_non_string_effect_receipt_key_that_aliases_source_generation(self):
        for expert_id, required_postcondition, suffix in _DIALECTS:
            with self.subTest(expert_id=expert_id):
                receipt = {
                    "receipt_id": "edit:42",
                    "capability": "filesystem_write",
                    AuthorityForgingKey("source_generation"): "project:4",
                }
                result = successful_apply_result(
                    receipt=receipt,
                    postcondition=canonical_postcondition(
                        expert_id,
                        required_postcondition,
                        suffix,
                    ),
                )
                registry, budget = invoke_apply(expert_id, result)
                self.assertEqual(len(registry.calls), 1)
                self.assertEqual(registry.calls[0][3], 0)
                self.assertEqual(budget.model_calls_used, 0)

    def test_rejects_non_string_postcondition_key_that_aliases_source_generation(self):
        for expert_id, required_postcondition, suffix in _DIALECTS:
            with self.subTest(expert_id=expert_id):
                receipt = {
                    "receipt_id": "edit:42",
                    "capability": "filesystem_write",
                    "source_generation": "project:4",
                }
                postcondition = canonical_postcondition(
                    expert_id,
                    required_postcondition,
                    suffix,
                )
                source_generation = postcondition.pop("source_generation")
                postcondition[AuthorityForgingKey("source_generation")] = source_generation
                result = successful_apply_result(
                    receipt=receipt,
                    postcondition=postcondition,
                )
                registry, budget = invoke_apply(expert_id, result)
                self.assertEqual(len(registry.calls), 1)
                self.assertEqual(registry.calls[0][3], 0)
                self.assertEqual(budget.model_calls_used, 0)


if __name__ == "__main__":
    unittest.main()
