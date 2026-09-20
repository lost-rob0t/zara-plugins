import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.composition import (
    CompositionError,
    InvocationFence,
    InvocationResult,
    MetaExpertComposer,
    SharedSymbolicBudget,
)


class SymbolicBudgetAuthorityTests(unittest.TestCase):
    def _fence(self):
        return InvocationFence(
            workspace_id="workspace",
            workspace_generation=3,
            is_cancelled=lambda: False,
            is_current_generation=lambda workspace, generation: (
                workspace == "workspace" and generation == 3
            ),
        )

    def test_invoker_cannot_reset_or_widen_shared_budget(self):
        budget = SharedSymbolicBudget(
            max_invocations=1,
            max_depth=2,
            max_evidence=1,
        )

        def invoke(*args, budget, **kwargs):
            budget.max_invocations = 99
            budget.invocations_used = 0
            budget.max_evidence = 99
            budget.evidence_used = 0
            return InvocationResult(status="succeeded")

        with self.assertRaisesRegex(CompositionError, "mutated shared symbolic budget"):
            MetaExpertComposer(invoke).invoke(
                "zara:expert/test",
                "query",
                {},
                budget=budget,
                fence=self._fence(),
            )

        self.assertEqual(budget.max_invocations, 1)
        self.assertEqual(budget.invocations_used, 1)
        self.assertEqual(budget.max_evidence, 1)
        self.assertEqual(budget.evidence_used, 0)
        self.assertEqual(budget.model_calls_used, 0)

    def test_invoker_cannot_false_green_exact_zero_model_ledger(self):
        budget = SharedSymbolicBudget()

        def invoke(*args, budget, **kwargs):
            budget.max_model_calls = False
            budget.model_calls_used = 0.0
            return InvocationResult(status="succeeded")

        with self.assertRaisesRegex(CompositionError, "mutated shared symbolic budget"):
            MetaExpertComposer(invoke).invoke(
                "zara:expert/test",
                "query",
                {},
                budget=budget,
                fence=self._fence(),
            )

        self.assertIs(type(budget.max_model_calls), int)
        self.assertIs(type(budget.model_calls_used), int)
        self.assertEqual(budget.max_model_calls, 0)
        self.assertEqual(budget.model_calls_used, 0)

    def test_invoker_cannot_shadow_budget_authority_guard(self):
        budget = SharedSymbolicBudget(max_invocations=1)

        def invoke(*args, budget, **kwargs):
            budget.assert_unchanged_by_invoker = lambda snapshot: None
            budget.max_invocations = 99
            return InvocationResult(status="succeeded")

        with self.assertRaisesRegex(CompositionError, "mutated shared symbolic budget"):
            MetaExpertComposer(invoke).invoke(
                "zara:expert/test",
                "query",
                {},
                budget=budget,
                fence=self._fence(),
            )

        self.assertEqual(budget.max_invocations, 1)
        self.assertEqual(budget.invocations_used, 1)
        self.assertNotIn("assert_unchanged_by_invoker", vars(budget))


if __name__ == "__main__":
    unittest.main()
