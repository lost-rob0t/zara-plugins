import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.composition import (
    HostExpertInvoker,
    InvocationFence,
    MetaExpertComposer,
    RegisteredPredicateBinding,
    SharedSymbolicBudget,
)


class HostResultStatusContractTests(unittest.TestCase):
    @staticmethod
    def _fence():
        return InvocationFence(
            workspace_id="status-contract",
            workspace_generation=1,
            is_cancelled=lambda: False,
            is_current_generation=lambda workspace, generation: (
                workspace == "status-contract" and generation == 1
            ),
        )

    def _invoke(self, ok):
        class Host:
            def query(self, namespace, predicate, arguments):
                return {
                    "ok": ok,
                    "results": [{"proved": True}],
                    "trace": ["fact:status"],
                }

        invoker = HostExpertInvoker(
            Host(),
            binding_for=lambda expert_id, operation, input_data: RegisteredPredicateBinding(
                namespace="status",
                predicate="verified",
                arguments=(),
            ),
        )
        budget = SharedSymbolicBudget()
        tree = MetaExpertComposer(invoker).invoke(
            "zara:expert/status",
            "verify",
            {},
            budget=budget,
            fence=self._fence(),
        )
        self.assertEqual(budget.max_model_calls, 0)
        self.assertEqual(budget.model_calls_used, 0)
        return tree

    def test_only_literal_true_can_succeed(self):
        self.assertEqual(self._invoke(True).status, "succeeded")
        self.assertEqual(self._invoke(False).status, "failed")

        for value in (1, 1.0, "true", [1], {"ok": True}):
            with self.subTest(value=value):
                self.assertEqual(self._invoke(value).status, "unknown")


if __name__ == "__main__":
    unittest.main()
