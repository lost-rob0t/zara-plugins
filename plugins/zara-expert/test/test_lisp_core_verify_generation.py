import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.composition import InvocationFence, SharedSymbolicBudget
from zara_expert.domain import ExpertHost
from zara_expert.lisp_composition import CoreLispFamilyCompositionInvoker
from zara_expert.lisp_family import make_lisp_expert_handler, register_lisp_family


class PendingCommonLispVerificationBackend:
    def run(self, request):
        capability = request["capability"]
        return {
            "ok": True,
            "results": [
                "repair_verification(expert('zara:expert/common-lisp'),"
                "verified(false),"
                "required_postcondition(sbcl_fresh_reader_and_compile_evidence))"
            ],
            "trace": [
                f"{capability.namespace}:{capability.predicate}/{capability.arity}"
            ],
        }


class ReceiptResolver:
    def __init__(self):
        self.calls = []

    def __call__(
        self,
        *,
        expert_id,
        source_generation,
        candidate_sha256,
        required_postcondition,
    ):
        query = {
            "expert_id": expert_id,
            "source_generation": source_generation,
            "candidate_sha256": candidate_sha256,
            "required_postcondition": required_postcondition,
        }
        self.calls.append(query)
        return {
            **query,
            "receipt_ref": (
                "zara.verified-outcome/v1:outcome:postcondition/"
                "common-lisp-core-generation"
            ),
            "verified": True,
            "fresh": True,
        }


class PassThroughCoreRegistry:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def invoke(self, handle, operation, payload, *, limits):
        self.calls.append(
            {
                "handle": handle,
                "operation": operation,
                "payload": dict(payload),
                "max_model_calls": limits.max_model_calls,
            }
        )
        outcome = self.handler(expert_operation=operation, **payload)
        return SimpleNamespace(
            verdict=SimpleNamespace(value=outcome["verdict"]),
            data=outcome["data"],
            evidence_refs=tuple(outcome["evidence_refs"]),
            usage=outcome["usage"],
            effect_receipts=tuple(outcome["effect_receipts"]),
        )


class CoreLimits:
    def __init__(self, *, max_model_calls):
        self.max_model_calls = max_model_calls


def current_fence():
    return InvocationFence(
        workspace_id="project",
        workspace_generation=9,
        is_cancelled=lambda: False,
        is_current_generation=lambda workspace, generation: (
            workspace == "project" and generation == 9
        ),
    )


class LispCoreVerifyGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        brain = root / "expert.pl"
        brain.write_text("% registered predicate fixture\n", encoding="utf-8")
        self.host = ExpertHost(
            PendingCommonLispVerificationBackend(),
            state_root=root / "state",
        )
        register_lisp_family(
            self.host,
            {
                "lisp": [brain],
                "common-lisp": [brain],
                "emacs-lisp": [brain],
            },
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_core_bridge_preserves_generation_for_verified_outcome_lookup(self):
        candidate = "(defun demo (x) (list x))"
        generation = "buffer:9"
        resolver = ReceiptResolver()
        registry = PassThroughCoreRegistry(
            make_lisp_expert_handler(
                self.host,
                "zara:expert/common-lisp",
                verified_outcome_resolver=resolver,
            )
        )
        handle = SimpleNamespace(
            expert_id="zara:expert/common-lisp",
            workspace="project",
        )
        invoker = CoreLispFamilyCompositionInvoker(
            registry,
            activation_for=lambda _expert_id, _fence: handle,
            limits_factory=CoreLimits,
        )
        budget = SharedSymbolicBudget(max_model_calls=0)

        result = invoker(
            "zara:expert/common-lisp",
            "repair.verify",
            {
                "arguments": ["(defun demo (x) (list x", candidate],
                "source_generation": generation,
            },
            budget=budget,
            fence=current_fence(),
            parent_path=(),
        )

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.model_calls, 0)
        self.assertEqual(budget.model_calls_used, 0)
        self.assertEqual(
            registry.calls[0]["payload"],
            {
                "arguments": ["(defun demo (x) (list x", candidate],
                "source_generation": generation,
            },
        )
        self.assertEqual(registry.calls[0]["max_model_calls"], 0)
        self.assertEqual(
            resolver.calls,
            [
                {
                    "expert_id": "zara:expert/common-lisp",
                    "source_generation": generation,
                    "candidate_sha256": hashlib.sha256(
                        candidate.encode("utf-8")
                    ).hexdigest(),
                    "required_postcondition": (
                        "sbcl_fresh_reader_and_compile_evidence"
                    ),
                }
            ],
        )
        self.assertIn(
            "zara.verified-outcome/v1:outcome:postcondition/"
            "common-lisp-core-generation",
            result.evidence,
        )


if __name__ == "__main__":
    unittest.main()
