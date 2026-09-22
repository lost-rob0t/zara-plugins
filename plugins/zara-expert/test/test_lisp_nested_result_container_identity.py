from types import SimpleNamespace
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert import CoreLispFamilyCompositionInvoker
from zara_expert.composition import InvocationFence, SharedSymbolicBudget


DIALECTS = (
    "zara:expert/common-lisp",
    "zara:expert/emacs-lisp",
)


class MutableNestedMapping(dict):
    """Non-canonical nested container that remains mutable after validation."""


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


def successful_predicate_result(nested_result):
    return SimpleNamespace(
        verdict=SimpleNamespace(value="succeeded"),
        data={"result": nested_result},
        evidence_refs=("ev:core:lisp",),
        usage={"model_calls": 0},
        effect_receipts=(),
    )


class LispNestedResultContainerIdentityTests(unittest.TestCase):
    def test_rejects_nested_custom_mapping_before_durable_projection(self):
        for expert_id in DIALECTS:
            with self.subTest(expert_id=expert_id):
                details = MutableNestedMapping(
                    {
                        "balanced": True,
                        "forms": [{"kind": "list", "depth": 1}],
                    }
                )
                nested_result = {
                    "ok": True,
                    "results": ["balanced(true)"],
                    "trace": ["structural-check"],
                    "details": details,
                    "model_calls": 0,
                    "effect_receipts": [],
                }
                registry = RecordingCoreRegistry(successful_predicate_result(nested_result))
                handle = SimpleNamespace(expert_id=expert_id, workspace="project")
                invoker = CoreLispFamilyCompositionInvoker(
                    registry,
                    activation_for=lambda _expert_id, _fence: handle,
                    limits_factory=CoreLimits,
                )
                budget = SharedSymbolicBudget(max_invocations=1, max_model_calls=0)

                with self.assertRaisesRegex(
                    Exception,
                    "Lisp symbolic result.*built-in dict",
                ):
                    invoker(
                        expert_id,
                        "structural.check",
                        {"arguments": ["(print 1)"]},
                        budget=budget,
                        fence=current_fence(),
                        parent_path=(),
                    )

                self.assertEqual(budget.model_calls_used, 0)
                self.assertEqual(registry.calls[0][3].max_model_calls, 0)


if __name__ == "__main__":
    unittest.main()
