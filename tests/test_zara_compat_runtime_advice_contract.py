from __future__ import annotations

import unittest

from scripts.zara_compat_runtime import CompatibilityRuntime


class CompatibilityRuntimeAdviceContractTest(unittest.TestCase):
    def test_unknown_advice_kind_is_rejected(self) -> None:
        runtime = CompatibilityRuntime("example")
        with self.assertRaisesRegex(ValueError, "unknown hook kind"):
            runtime.register_agent_loop_advice("maybe", 0, lambda: None)

    def test_advice_priority_matches_core_integer_bounds(self) -> None:
        runtime = CompatibilityRuntime("example")
        for priority in (True, 1.5, 100_001, -100_001):
            with self.subTest(priority=priority):
                with self.assertRaises(ValueError):
                    runtime.register_agent_loop_advice("before", priority, lambda: None)

    def test_advice_callback_must_be_callable(self) -> None:
        runtime = CompatibilityRuntime("example")
        with self.assertRaisesRegex(ValueError, "callback"):
            runtime.register_agent_loop_advice("after", 0, None)


if __name__ == "__main__":
    unittest.main()
