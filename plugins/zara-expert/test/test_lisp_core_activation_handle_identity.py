import sys
import unittest
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


class ForgedText(str):
    """String-shaped activation identity that lies about equality."""

    def __eq__(self, other):
        del other
        return True

    def __ne__(self, other):
        del other
        return False


class CoreLimits:
    def __init__(self, *, max_model_calls):
        self.max_model_calls = max_model_calls


class RecordingRegistry:
    def __init__(self):
        self.calls = []

    def invoke(self, handle, operation, payload, *, limits):
        self.calls.append((handle, operation, payload, limits.max_model_calls))
        return SimpleNamespace(
            verdict="succeeded",
            data={"result": {"ok": True}},
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


class LispCoreActivationHandleIdentityTests(unittest.TestCase):
    def _assert_rejected_before_core_invoke(self, expert_id, handle):
        registry = RecordingRegistry()
        invoker = CoreLispFamilyCompositionInvoker(
            registry,
            activation_for=lambda requested_expert_id, fence: handle,
            limits_factory=CoreLimits,
        )
        budget = SharedSymbolicBudget(max_invocations=1, max_model_calls=0)

        with self.assertRaises(CompositionError):
            invoker(
                expert_id,
                "structural.check",
                {"arguments": ["(list 1 2)"]},
                budget=budget,
                fence=current_fence(),
                parent_path=(),
            )

        self.assertEqual(registry.calls, [])
        self.assertEqual(budget.model_calls_used, 0)

    def test_rejects_forged_activation_expert_identity_before_core_invoke(self):
        for expert_id in LISP_EXPERTS:
            with self.subTest(expert_id=expert_id):
                handle = SimpleNamespace(
                    expert_id=ForgedText("zara:expert/not-the-requested-expert"),
                    workspace="project",
                )
                self._assert_rejected_before_core_invoke(expert_id, handle)

    def test_rejects_forged_activation_workspace_before_core_invoke(self):
        for expert_id in LISP_EXPERTS:
            with self.subTest(expert_id=expert_id):
                handle = SimpleNamespace(
                    expert_id=expert_id,
                    workspace=ForgedText("wrong-project"),
                )
                self._assert_rejected_before_core_invoke(expert_id, handle)


if __name__ == "__main__":
    unittest.main()
