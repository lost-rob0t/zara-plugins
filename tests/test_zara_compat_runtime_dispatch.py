from __future__ import annotations

import unittest

from scripts.zara_compat_runtime import CompatibilityRuntime


class _Command:
    pass


class CompatibilityRuntimeDispatchTest(unittest.TestCase):
    def test_dispatch_rejects_non_runtime_command(self) -> None:
        runtime = CompatibilityRuntime("example", command_type=_Command)
        future = runtime.dispatch(object())
        with self.assertRaises(TypeError):
            future.result()

    def test_closed_runtime_rejects_dispatch(self) -> None:
        runtime = CompatibilityRuntime("example", command_type=_Command)
        runtime._shutdown()
        future = runtime.dispatch(_Command())
        with self.assertRaises(RuntimeError):
            future.result()


if __name__ == "__main__":
    unittest.main()
