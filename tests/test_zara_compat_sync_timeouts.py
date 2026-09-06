from __future__ import annotations

import threading
import time
import unittest

from scripts.zara_compat import collect_service_tools
from scripts.zara_compat_runtime import exercise_service_lifecycle


class ZaraCompatibilitySyncTimeoutTest(unittest.TestCase):
    @staticmethod
    def _release_later(event: threading.Event) -> threading.Timer:
        timer = threading.Timer(1.0, event.set)
        timer.daemon = True
        timer.start()
        return timer

    def test_blocked_sync_tools_returns_at_deadline_not_worker_completion(self) -> None:
        release = threading.Event()
        self._release_later(release)

        class Service:
            def tools(self):
                release.wait()
                return ()

        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            collect_service_tools(Service(), timeout=0.01)
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.5)

    def test_blocked_sync_lifecycle_returns_at_deadline_not_worker_completion(self) -> None:
        release = threading.Event()
        self._release_later(release)

        class Service:
            def start(self, runtime) -> None:
                release.wait()

            def stop(self) -> None:
                return None

        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            exercise_service_lifecycle(Service(), object(), timeout=0.01)
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.5)


if __name__ == "__main__":
    unittest.main()
