from __future__ import annotations

import unittest

from scripts.zara_compat_runtime import exercise_service_lifecycle


class AsyncServiceLifecycleCompatibilityTest(unittest.TestCase):
    def test_async_start_and_stop_are_executed(self) -> None:
        calls: list[str] = []

        class Service:
            async def start(self, runtime) -> None:
                calls.append("start")

            async def stop(self) -> None:
                calls.append("stop")

        class Runtime:
            def _shutdown(self) -> None:
                calls.append("shutdown")

        exercise_service_lifecycle(Service(), Runtime())

        self.assertEqual(calls, ["start", "stop", "shutdown"])

    def test_async_start_failure_still_executes_stop_and_shutdown(self) -> None:
        calls: list[str] = []

        class Service:
            async def start(self, runtime) -> None:
                calls.append("start")
                raise RuntimeError("boom")

            async def stop(self) -> None:
                calls.append("stop")

        class Runtime:
            def _shutdown(self) -> None:
                calls.append("shutdown")

        with self.assertRaisesRegex(RuntimeError, "boom"):
            exercise_service_lifecycle(Service(), Runtime())

        self.assertEqual(calls, ["start", "stop", "shutdown"])


if __name__ == "__main__":
    unittest.main()
