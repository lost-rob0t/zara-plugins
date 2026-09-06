from __future__ import annotations

import asyncio
import threading
import time
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

    def test_sync_tools_timeout_does_not_wait_for_worker_shutdown(self) -> None:
        release = threading.Event()

        class Service:
            def tools(self):
                release.wait(1.0)
                return []

        started = time.monotonic()
        try:
            with self.assertRaises(TimeoutError):
                collect_service_tools(Service(), timeout=0.01)
        finally:
            release.set()

        self.assertLess(time.monotonic() - started, 0.2)

    def test_sync_tools_propagate_plugin_exception(self) -> None:
        class Service:
            def tools(self):
                raise ValueError("broken tools")

        with self.assertRaisesRegex(ValueError, "broken tools"):
            collect_service_tools(Service(), timeout=0.1)

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

    def test_sync_start_timeout_does_not_wait_for_worker_shutdown(self) -> None:
        release = threading.Event()
        calls: list[str] = []

        class Service:
            def start(self, runtime) -> None:
                release.wait(1.0)

            def stop(self) -> None:
                calls.append("stop")

        class Runtime:
            def _shutdown(self) -> None:
                calls.append("shutdown")

        started = time.monotonic()
        try:
            with self.assertRaises(TimeoutError):
                exercise_service_lifecycle(Service(), Runtime(), timeout=0.01)
        finally:
            release.set()

        self.assertLess(time.monotonic() - started, 0.2)
        self.assertEqual(calls, ["stop", "shutdown"])

    def test_sync_stop_timeout_does_not_wait_for_worker_shutdown(self) -> None:
        release = threading.Event()
        calls: list[str] = []

        class Service:
            def start(self, runtime) -> None:
                calls.append("start")

            def stop(self) -> None:
                release.wait(1.0)

        class Runtime:
            def _shutdown(self) -> None:
                calls.append("shutdown")

        started = time.monotonic()
        try:
            with self.assertRaises(TimeoutError):
                exercise_service_lifecycle(Service(), Runtime(), timeout=0.01)
        finally:
            release.set()

        self.assertLess(time.monotonic() - started, 0.2)
        self.assertEqual(calls, ["start", "shutdown"])


if __name__ == "__main__":
    unittest.main()
