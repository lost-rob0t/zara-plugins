from __future__ import annotations

import unittest

from scripts.zara_compat_runtime import CompatibilityRuntime


class CompatibilityRuntimeWorkerSignatureTest(unittest.TestCase):
    def test_worker_target_must_accept_core_stop_event(self) -> None:
        runtime = CompatibilityRuntime("example")

        def invalid_target() -> None:
            return None

        with self.assertRaisesRegex(TypeError, "stop_event"):
            runtime.start_worker("invalid", invalid_target)


if __name__ == "__main__":
    unittest.main()
