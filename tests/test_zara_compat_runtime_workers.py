from __future__ import annotations

import os
import threading
import unittest
from unittest import mock

from scripts.zara_compat_runtime import CompatibilityRuntime, fake_dependency_environment


def _worker(_stop_event) -> None:
    return None


class CompatibilityRuntimeWorkerTest(unittest.TestCase):
    def test_discord_compatibility_never_enables_live_credentials(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with fake_dependency_environment("zara-discord"):
                self.assertNotIn("ZARA_DISCORD_TOKEN", os.environ)

    def test_valid_worker_is_registered(self) -> None:
        runtime = CompatibilityRuntime("example")
        worker = runtime.start_worker("events", _worker)
        self.assertEqual(worker.name, "example-events")

    def test_managed_worker_runs_and_stops_with_runtime(self) -> None:
        runtime = CompatibilityRuntime("example")
        started = threading.Event()
        stopped = threading.Event()

        def target(stop_event: threading.Event) -> None:
            started.set()
            stop_event.wait(timeout=1.0)
            if stop_event.is_set():
                stopped.set()

        worker = runtime.start_worker("events", target)

        self.assertTrue(started.wait(timeout=0.25))
        self.assertTrue(worker.is_alive)
        runtime._shutdown()
        self.assertTrue(stopped.wait(timeout=0.25))
        self.assertFalse(worker.is_alive)

    def test_worker_name_must_be_bounded(self) -> None:
        runtime = CompatibilityRuntime("example")
        for name in ("", "x" * 65):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    runtime.start_worker(name, _worker)

    def test_worker_target_must_be_callable(self) -> None:
        runtime = CompatibilityRuntime("example")
        with self.assertRaises(TypeError):
            runtime.start_worker("events", None)

    def test_duplicate_worker_name_is_rejected(self) -> None:
        runtime = CompatibilityRuntime("example")
        runtime.start_worker("events", _worker)
        with self.assertRaises(ValueError):
            runtime.start_worker("events", _worker)

    def test_worker_limit_matches_zara_runtime(self) -> None:
        runtime = CompatibilityRuntime("example")
        for index in range(8):
            runtime.start_worker(f"worker-{index}", _worker)
        with self.assertRaises(RuntimeError):
            runtime.start_worker("worker-8", _worker)

    def test_closed_runtime_rejects_new_workers(self) -> None:
        runtime = CompatibilityRuntime("example")
        runtime._shutdown()
        with self.assertRaises(RuntimeError):
            runtime.start_worker("events", _worker)


if __name__ == "__main__":
    unittest.main()
