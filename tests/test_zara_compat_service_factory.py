from __future__ import annotations

import threading
import time
import unittest

from scripts.zara_compat import construct_service_plugin


class ServiceFactoryCompatibilityTest(unittest.TestCase):
    def test_blocked_sync_factory_returns_at_deadline(self) -> None:
        release = threading.Event()

        def factory():
            release.wait(1.0)
            return object()

        started = time.monotonic()
        try:
            with self.assertRaises(TimeoutError):
                construct_service_plugin(factory, timeout=0.01)
        finally:
            release.set()

        self.assertLess(time.monotonic() - started, 0.2)

    def test_completed_factory_propagates_plugin_exception(self) -> None:
        def factory():
            raise ValueError("broken factory")

        with self.assertRaisesRegex(ValueError, "broken factory"):
            construct_service_plugin(factory, timeout=0.1)


if __name__ == "__main__":
    unittest.main()
