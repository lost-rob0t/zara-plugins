import hashlib
from types import SimpleNamespace
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert import CoreLispFamilyCompositionInvoker
from zara_expert.composition import InvocationFence, SharedSymbolicBudget


DIALECTS = {
    "zara:expert/common-lisp": "sbcl_fresh_reader_and_compile_evidence",
    "zara:expert/emacs-lisp": "emacs_fresh_reader_and_byte_compile_evidence",
}


class RecordingCoreRegistry:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def invoke(self, handle, operation, payload, *, limits):
        self.calls.append((handle, operation, dict(payload), limits))
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


def successful_apply_result(expert_id, required_postcondition, receipt, postcondition_ref):
    replacement = "(print 1)"
    postcondition = {
        "checker": "dialect-reader",
        "expert_id": expert_id,
        "verified": True,
        "fresh": True,
        "source_generation": "project:4",
        "observed_generation": "project:5",
        "candidate_sha256": hashlib.sha256(replacement.encode("utf-8")).hexdigest(),
        "required_postcondition": required_postcondition,
        "receipt_ref": postcondition_ref,
    }
    return (
        SimpleNamespace(
            verdict=SimpleNamespace(value="succeeded"),
            data={
                "effect_receipt": receipt,
                "postcondition_evidence": postcondition,
            },
            evidence_refs=(postcondition_ref,),
            usage={"model_calls": 0},
            effect_receipts=(receipt,),
        ),
        postcondition,
    )


def successful_verify_result(expert_id, required_postcondition, nested_result, postcondition_ref):
    candidate = "(print 1)"
    candidate_sha256 = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    postcondition = {
        "receipt_ref": postcondition_ref,
        "required_postcondition": required_postcondition,
        "source_generation": "project:4",
        "candidate_sha256": candidate_sha256,
    }
    return SimpleNamespace(
        verdict=SimpleNamespace(value="succeeded"),
        data={
            "result": nested_result,
            "verified": True,
            "verified_outcome_ref": postcondition_ref,
            "postcondition_evidence": postcondition,
        },
        evidence_refs=(postcondition_ref,),
        usage={"model_calls": 0},
        effect_receipts=(),
    )


class LispAuthoritySnapshotTests(unittest.TestCase):
    def test_effect_success_detaches_authority_projection_from_core_owned_mutable_dicts(self):
        for expert_id, required_postcondition in DIALECTS.items():
            with self.subTest(expert_id=expert_id):
                receipt = {
                    "receipt_id": "edit:42",
                    "capability": "filesystem_write",
                    "source_generation": "project:4",
                }
                postcondition_ref = (
                    "zara.verified-outcome/v1:outcome:postcondition/"
                    + expert_id.rsplit("/", 1)[-1]
                    + "-project-5"
                )
                core_result, postcondition = successful_apply_result(
                    expert_id,
                    required_postcondition,
                    receipt,
                    postcondition_ref,
                )
                registry = RecordingCoreRegistry(core_result)
                handle = SimpleNamespace(expert_id=expert_id, workspace="project")
                invoker = CoreLispFamilyCompositionInvoker(
                    registry,
                    activation_for=lambda _expert_id, _fence: handle,
                    limits_factory=CoreLimits,
                )
                budget = SharedSymbolicBudget(max_invocations=1, max_model_calls=0)

                result = invoker(
                    expert_id,
                    "repair.apply",
                    {
                        "repair": {"replacement": "(print 1)"},
                        "expected_preimage": "(print 1",
                        "source_generation": "project:4",
                    },
                    budget=budget,
                    fence=current_fence(),
                    parent_path=(),
                )

                self.assertEqual(result.status, "succeeded")
                self.assertEqual(budget.model_calls_used, 0)
                self.assertEqual(registry.calls[0][3].max_model_calls, 0)

                receipt["receipt_id"] = "edit:forged-late"
                receipt["source_generation"] = "project:forged-late"
                postcondition["verified"] = False
                postcondition["fresh"] = False
                postcondition["receipt_ref"] = (
                    "zara.verified-outcome/v1:outcome:postcondition/forged-late"
                )

                self.assertEqual(result.data["effect_receipt"]["receipt_id"], "edit:42")
                self.assertEqual(
                    result.data["effect_receipt"]["source_generation"],
                    "project:4",
                )
                self.assertIs(result.data["postcondition_evidence"]["verified"], True)
                self.assertIs(result.data["postcondition_evidence"]["fresh"], True)
                self.assertEqual(
                    result.data["postcondition_evidence"]["receipt_ref"],
                    postcondition_ref,
                )
                self.assertEqual(budget.model_calls_used, 0)

    def test_verify_success_detaches_symbolic_result_from_late_core_mutation(self):
        for expert_id, required_postcondition in DIALECTS.items():
            with self.subTest(expert_id=expert_id):
                nested_details = {
                    "phase": "reader",
                    "observations": ["balanced-after-repair"],
                    "provenance": {"engine": "symbolic"},
                }
                nested_result = {
                    "ok": True,
                    "results": ["verified(false)"],
                    "trace": ["structural-check"],
                    "details": nested_details,
                    "model_calls": 0,
                    "effect_receipts": [],
                }
                postcondition_ref = (
                    "zara.verified-outcome/v1:outcome:postcondition/"
                    + expert_id.rsplit("/", 1)[-1]
                    + "-project-5"
                )
                core_result = successful_verify_result(
                    expert_id,
                    required_postcondition,
                    nested_result,
                    postcondition_ref,
                )
                registry = RecordingCoreRegistry(core_result)
                handle = SimpleNamespace(expert_id=expert_id, workspace="project")
                invoker = CoreLispFamilyCompositionInvoker(
                    registry,
                    activation_for=lambda _expert_id, _fence: handle,
                    limits_factory=CoreLimits,
                )
                budget = SharedSymbolicBudget(max_invocations=1, max_model_calls=0)

                result = invoker(
                    expert_id,
                    "repair.verify",
                    {
                        "arguments": ["(print 1", "(print 1)"],
                        "source_generation": "project:4",
                    },
                    budget=budget,
                    fence=current_fence(),
                    parent_path=(),
                )

                self.assertEqual(result.status, "succeeded")
                self.assertEqual(budget.model_calls_used, 0)
                self.assertEqual(registry.calls[0][3].max_model_calls, 0)

                nested_result["ok"] = False
                nested_result["results"][0] = "forged-late-result"
                nested_result["trace"].append("forged-late-trace")
                nested_details["phase"] = "forged-late-phase"
                nested_details["observations"].append("forged-late-observation")
                nested_details["provenance"]["engine"] = "forged-late-engine"

                self.assertIs(result.data["result"]["ok"], True)
                self.assertEqual(result.data["result"]["results"], ["verified(false)"])
                self.assertEqual(result.data["result"]["trace"], ["structural-check"])
                self.assertEqual(result.data["result"]["details"]["phase"], "reader")
                self.assertEqual(
                    result.data["result"]["details"]["observations"],
                    ["balanced-after-repair"],
                )
                self.assertEqual(
                    result.data["result"]["details"]["provenance"],
                    {"engine": "symbolic"},
                )
                self.assertEqual(budget.model_calls_used, 0)


if __name__ == "__main__":
    unittest.main()
