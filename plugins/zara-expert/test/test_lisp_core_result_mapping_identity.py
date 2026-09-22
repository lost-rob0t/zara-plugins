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


class CoreLimits:
    def __init__(self, *, max_model_calls):
        self.max_model_calls = max_model_calls


class RecordingRegistry:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def invoke(self, handle, operation, payload, *, limits):
        self.calls.append((handle, operation, payload, limits.max_model_calls))
        return SimpleNamespace(
            verdict="succeeded",
            data=self.data,
            evidence_refs=("ev:core:lisp",),
            effect_receipts=(),
            usage={"model_calls": 0},
        )


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


class LispCoreResultMappingIdentityTests(unittest.TestCase):
    def _assert_rejected_after_core_invoke(self, expert_id, data):
        registry = RecordingRegistry(data)
        invoker = CoreLispFamilyCompositionInvoker(
            registry,
            activation_for=lambda requested_expert_id, fence: handle_for(requested_expert_id),
            limits_factory=CoreLimits,
        )
        budget = SharedSymbolicBudget(max_invocations=1, max_model_calls=0)

        with self.assertRaisesRegex(CompositionError, "built-in dict"):
            invoker(
                expert_id,
                "structural.check",
                {"arguments": ["(list 1 2)"]},
                budget=budget,
                fence=current_fence(),
                parent_path=(),
            )

        self.assertEqual(len(registry.calls), 1)
        self.assertEqual(registry.calls[0][3], 0)
        self.assertEqual(budget.model_calls_used, 0)

    def test_rejects_custom_core_data_mapping_before_projection(self):
        for expert_id in LISP_EXPERTS:
            with self.subTest(expert_id=expert_id):
                self._assert_rejected_after_core_invoke(
                    expert_id,
                    UserDict({"result": {"ok": True}}),
                )

    def test_rejects_custom_nested_result_mapping_before_projection(self):
        for expert_id in LISP_EXPERTS:
            with self.subTest(expert_id=expert_id):
                self._assert_rejected_after_core_invoke(
                    expert_id,
                    {"result": UserDict({"ok": True})},
                )


if __name__ == "__main__":
    unittest.main()
