import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.composition import CompositionError, InvocationFence, SharedSymbolicBudget
from zara_expert.domain import ExpertError
from zara_expert.lisp_composition import (
    CoreLispFamilyCompositionInvoker,
    LispFamilyCompositionInvoker,
)
from zara_expert.lisp_family import invoke_lisp_operation, make_lisp_expert_handler


class RecordingRegistry:
    def __init__(self):
        self.calls = []

    def invoke(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError("malformed Lisp input must fail before Core dispatch")


def current_fence():
    return InvocationFence(
        workspace_id="project",
        workspace_generation=4,
        is_cancelled=lambda: False,
        is_current_generation=lambda workspace, generation: (
            workspace == "project" and generation == 4
        ),
    )


class LispFailClosedInputShapeTests(unittest.TestCase):
    def test_low_level_dispatch_rejects_unhashable_expert_identity(self):
        with self.assertRaisesRegex(ExpertError, "expert identity must be a string"):
            invoke_lisp_operation(object(), [], "structural.check", ["(ok)"])

    def test_low_level_dispatch_rejects_unhashable_operation(self):
        with self.assertRaisesRegex(ExpertError, "operation must be a string"):
            invoke_lisp_operation(object(), "zara:expert/lisp", [], ["(ok)"])

    def test_handler_constructor_rejects_unhashable_expert_identity(self):
        with self.assertRaisesRegex(ExpertError, "expert identity must be a string"):
            make_lisp_expert_handler(object(), [])

    def test_handler_rejects_unhashable_operation_before_host_dispatch(self):
        handler = make_lisp_expert_handler(object(), "zara:expert/lisp")
        with self.assertRaisesRegex(ExpertError, "operation must be a string"):
            handler(expert_operation=[], arguments=["(ok)"])

    def test_local_composition_rejects_unhashable_identity_and_operation(self):
        invoker = LispFamilyCompositionInvoker(object())
        budget = SharedSymbolicBudget(max_model_calls=0)
        fence = current_fence()

        with self.assertRaisesRegex(CompositionError, "expert identity must be a string"):
            invoker(
                [],
                "structural.check",
                {"arguments": ["(ok)"]},
                budget=budget,
                fence=fence,
                parent_path=(),
            )
        with self.assertRaisesRegex(CompositionError, "operation must be a string"):
            invoker(
                "zara:expert/lisp",
                [],
                {"arguments": ["(ok)"]},
                budget=budget,
                fence=fence,
                parent_path=(),
            )
        self.assertEqual(budget.model_calls_used, 0)

    def test_core_composition_rejects_shapes_before_activation_or_dispatch(self):
        registry = RecordingRegistry()
        activation_calls = []

        def activation_for(expert_id, fence):
            activation_calls.append((expert_id, fence.workspace_id))
            raise AssertionError("malformed Lisp input must fail before activation")

        invoker = CoreLispFamilyCompositionInvoker(
            registry,
            activation_for=activation_for,
            limits_factory=lambda **kwargs: kwargs,
        )
        budget = SharedSymbolicBudget(max_model_calls=0)
        fence = current_fence()

        with self.assertRaisesRegex(CompositionError, "expert identity must be a string"):
            invoker(
                [],
                "structural.check",
                {"arguments": ["(ok)"]},
                budget=budget,
                fence=fence,
                parent_path=(),
            )
        with self.assertRaisesRegex(CompositionError, "operation must be a string"):
            invoker(
                "zara:expert/lisp",
                [],
                {"arguments": ["(ok)"]},
                budget=budget,
                fence=fence,
                parent_path=(),
            )
        self.assertEqual(activation_calls, [])
        self.assertEqual(registry.calls, [])
        self.assertEqual(budget.model_calls_used, 0)


if __name__ == "__main__":
    unittest.main()
