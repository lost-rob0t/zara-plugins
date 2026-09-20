import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.composition import SharedSymbolicBudget


class SharedSymbolicBudgetContractTests(unittest.TestCase):
    def test_model_budget_requires_builtin_integer_zero(self):
        for invalid in (False, True, 0.0, 1.0, "0", None):
            with self.subTest(value=invalid):
                with self.assertRaisesRegex(
                    ValueError,
                    "max_model_calls must be a non-negative integer",
                ):
                    SharedSymbolicBudget(max_model_calls=invalid)

        with self.assertRaisesRegex(
            ValueError,
            "pure symbolic composition requires max_model_calls=0",
        ):
            SharedSymbolicBudget(max_model_calls=1)

        budget = SharedSymbolicBudget(max_model_calls=0)
        self.assertEqual(budget.max_model_calls, 0)
        self.assertIs(type(budget.max_model_calls), int)
        self.assertEqual(budget.model_calls_used, 0)


if __name__ == "__main__":
    unittest.main()
