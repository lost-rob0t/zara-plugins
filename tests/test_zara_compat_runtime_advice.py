from __future__ import annotations

import unittest

from scripts.zara_compat_runtime import CompatibilityRuntime


class CompatibilityRuntimeAdviceTest(unittest.TestCase):
    def test_closed_runtime_rejects_agent_loop_advice(self) -> None:
        runtime = CompatibilityRuntime("example")
        runtime._shutdown()
        with self.assertRaises(RuntimeError):
            runtime.register_agent_loop_advice("before_turn", 0, lambda: None)


if __name__ == "__main__":
    unittest.main()
