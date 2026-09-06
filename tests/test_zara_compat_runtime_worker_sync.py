from __future__ import annotations

import unittest

from scripts.zara_compat_runtime import CompatibilityRuntime


class CompatibilityRuntimeWorkerSyncTest(unittest.TestCase):
    def test_async_worker_target_is_rejected(self) -> None:
        runtime = CompatibilityRuntime("example")

        async def invalid_target(_stop_event) -> None:
            return None

        with self.assertRaisesRegex(TypeError, "synchronous"):
            runtime.start_worker("invalid", invalid_target)


if __name__ == "__main__":
    unittest.main()
