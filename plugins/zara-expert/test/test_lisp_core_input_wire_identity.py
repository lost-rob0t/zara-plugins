import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert import CoreLispFamilyCompositionInvoker
from zara_expert.composition import CompositionError, InvocationFence, SharedSymbolicBudget


DIALECT_EXPERTS = (
    "zara:expert/common-lisp",
    "zara:expert/emacs-lisp",
)


class ForgedText(str):
    """String-shaped authority value with caller-controlled comparison/encoding."""

    def encode(self, encoding="utf-8", errors="strict"):
        del encoding, errors
        return b"forged-wire-bytes"

    def __eq__(self, other):
        del other
        return True


class ForgedList(list):
    pass


class ForgedDict(dict):
    pass


class NeverRegistry:
    def __init__(self):
        self.calls = []

    def invoke(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError("malformed Lisp repair input reached canonical Core invoke")


class CoreLimits:
    def __init__(self, *, max_model_calls):
        self.max_model_calls = max_model_calls


def current_fence():
    return InvocationFence(
        workspace_id="project",
        workspace_generation=8,
        is_cancelled=lambda: False,
        is_current_generation=lambda workspace, generation: (
            workspace == "project" and generation == 8
        ),
    )


class LispCoreInputWireIdentityTests(unittest.TestCase):
    def _invoke(self, expert_id, operation, payload):
        registry = NeverRegistry()
        activations = []

        def activation_for(requested_expert_id, _fence):
            activations.append(requested_expert_id)
            raise AssertionError("malformed Lisp repair input reached activation")

        invoker = CoreLispFamilyCompositionInvoker(
            registry,
            activation_for=activation_for,
            limits_factory=CoreLimits,
        )
        budget = SharedSymbolicBudget(max_invocations=1, max_model_calls=0)
        with self.assertRaises(CompositionError):
            invoker(
                expert_id,
                operation,
                payload,
                budget=budget,
                fence=current_fence(),
                parent_path=(),
            )
        self.assertEqual(activations, [])
        self.assertEqual(registry.calls, [])
        self.assertEqual(budget.model_calls_used, 0)

    def test_verify_rejects_noncanonical_wire_values_before_activation(self):
        canonical = {
            "arguments": [
                "(defun demo (x) (list x",
                "(defun demo (x) (list x))",
            ],
            "source_generation": "buffer:8",
        }
        cases = (
            ForgedDict(canonical),
            {**canonical, "arguments": ForgedList(canonical["arguments"])},
            {
                **canonical,
                "arguments": [canonical["arguments"][0], ForgedText(canonical["arguments"][1])],
            },
            {**canonical, "source_generation": ForgedText("buffer:8")},
        )
        for expert_id in DIALECT_EXPERTS:
            for payload in cases:
                with self.subTest(expert_id=expert_id, payload_type=type(payload).__name__):
                    self._invoke(expert_id, "repair.verify", payload)

    def test_apply_rejects_noncanonical_effect_bindings_before_activation(self):
        canonical = {
            "repair": {"replacement": "(defun demo (x) (list x))"},
            "expected_preimage": "(defun demo (x) (list x",
            "source_generation": "buffer:8",
        }
        cases = (
            ForgedDict(canonical),
            {**canonical, "repair": ForgedDict(canonical["repair"])},
            {
                **canonical,
                "repair": {"replacement": ForgedText(canonical["repair"]["replacement"])},
            },
            {**canonical, "expected_preimage": ForgedText(canonical["expected_preimage"])},
            {**canonical, "source_generation": ForgedText("buffer:8")},
        )
        for expert_id in DIALECT_EXPERTS:
            for payload in cases:
                with self.subTest(expert_id=expert_id, payload_type=type(payload).__name__):
                    self._invoke(expert_id, "repair.apply", payload)


if __name__ == "__main__":
    unittest.main()
