from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert import CoreLispFamilyCompositionInvoker
from zara_expert.composition import CompositionError, InvocationFence, SharedSymbolicBudget


DIALECTS = (
    "zara:expert/common-lisp",
    "zara:expert/emacs-lisp",
)


class HostileUsage(dict):
    """Mapping subclass that must not cross the Core usage-ledger wire boundary."""


class HostileUsageKey(str):
    """String subclass that aliases the model_calls authority key."""

    def __new__(cls):
        return super().__new__(cls, "model_calls")

    def __eq__(self, other):
        return str(other) == "model_calls"

    def __hash__(self):
        return hash("model_calls")


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


def successful_predicate_result(usage):
    return SimpleNamespace(
        verdict=SimpleNamespace(value="succeeded"),
        data={
            "result": {
                "ok": True,
                "results": ["balanced(true)"],
                "trace": ["structural-check"],
                "model_calls": 0,
                "effect_receipts": [],
            },
        },
        evidence_refs=("ev:core:lisp",),
        usage=usage,
        effect_receipts=(),
    )


class LispUsageLedgerIdentityTests(unittest.TestCase):
    def _invoke_and_expect_closed(self, usage, pattern):
        for expert_id in DIALECTS:
            with self.subTest(expert_id=expert_id):
                registry = RecordingCoreRegistry(successful_predicate_result(usage))
                handle = SimpleNamespace(expert_id=expert_id, workspace="project")
                invoker = CoreLispFamilyCompositionInvoker(
                    registry,
                    activation_for=lambda _expert_id, _fence: handle,
                    limits_factory=CoreLimits,
                )
                budget = SharedSymbolicBudget(
                    max_invocations=1,
                    max_model_calls=0,
                )

                with self.assertRaisesRegex(CompositionError, pattern):
                    invoker(
                        expert_id,
                        "structural.check",
                        {"arguments": ["(print 1)"]},
                        budget=budget,
                        fence=current_fence(),
                        parent_path=(),
                    )

                self.assertEqual(len(registry.calls), 1)
                self.assertEqual(registry.calls[0][3].max_model_calls, 0)
                self.assertEqual(budget.model_calls_used, 0)

    def test_core_usage_mapping_subclass_fails_closed(self):
        self._invoke_and_expect_closed(
            HostileUsage({"model_calls": 0}),
            "Core Lisp expert usage ledger must be a built-in dict",
        )

    def test_core_usage_key_string_subclass_fails_closed(self):
        self._invoke_and_expect_closed(
            {HostileUsageKey(): 0},
            "Core Lisp expert usage ledger keys must be built-in strings",
        )


if __name__ == "__main__":
    unittest.main()
