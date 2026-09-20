import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.composition import InvocationFence, SharedSymbolicBudget
from zara_expert.lisp_composition import LispFamilyCompositionInvoker


class LispCompositionStatusContractTests(unittest.TestCase):
    @staticmethod
    def _fence():
        return InvocationFence(
            workspace_id="lisp-status-contract",
            workspace_generation=1,
            is_cancelled=lambda: False,
            is_current_generation=lambda workspace, generation: (
                workspace == "lisp-status-contract" and generation == 1
            ),
        )

    def _invoke(self, ok):
        budget = SharedSymbolicBudget()
        raw = {
            "ok": ok,
            "results": [{"proved": True}],
            "trace": ["fact:lisp-status"],
        }
        with patch(
            "zara_expert.lisp_composition.invoke_lisp_operation",
            return_value=raw,
        ):
            result = LispFamilyCompositionInvoker(object())(
                "zara:expert/lisp",
                "inspect",
                {"arguments": []},
                budget=budget,
                fence=self._fence(),
                parent_path=(),
            )
        self.assertEqual(budget.max_model_calls, 0)
        self.assertEqual(budget.model_calls_used, 0)
        return result

    def test_only_literal_true_can_succeed(self):
        self.assertEqual(self._invoke(True).status, "succeeded")
        self.assertEqual(self._invoke(False).status, "failed")

        for value in (1, 1.0, "true", [1], {"ok": True}):
            with self.subTest(value=value):
                self.assertEqual(self._invoke(value).status, "unknown")


if __name__ == "__main__":
    unittest.main()
