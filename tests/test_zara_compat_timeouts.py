from __future__ import annotations

import asyncio
import unittest

from scripts.zara_compat import collect_service_tools
from scripts.zara_compat_runtime import exercise_service_lifecycle


class CompatibilityLifecycleTimeoutTest(unittest.TestCase):
    def test_async_tools_respect_core_lifecycle_timeout(self) -> None:
        class Service:
            async def tools(self):
                await asyncio.sleep(0.05)
                return []

        with self.assertRaises(TimeoutError):
            collect_service_tools(Service(), timeout=0.001)

    def test_async_start_timeout_still_stops_and_shuts_down(self) -> None:
        calls: list[str] = []

        class Service:
            async def start(self, runtime) -> None:
                await asyncio.sleep(0.05)

            async def stop(self) -> None:
                calls.append("stop")

        class Runtime:
            def _shutdown(self) -> None:
                calls.append("shutdown")

        with self.assertRaises(TimeoutError):
            exercise_service_lifecycle(Service(), Runtime(), timeout=0.001)

        self.assertEqual(calls, ["stop", "shutdown"])


if __name__ == "__main__":
    unittest.main()
