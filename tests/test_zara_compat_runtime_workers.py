from __future__ import annotations

import os
import threading
import unittest
from unittest import mock

from scripts.zara_compat_runtime import CompatibilityRuntime, fake_dependency_environment


def _worker(_stop_event) -> None:
    return None


class CompatibilityRuntimeWorkerTest(unittest.TestCase):
    def test_fake_dependency_environment_strips_live_provider_credentials(self) -> None:
        cases = (
            ("zara-avatar", "ZARA_AVATAR_RENDERER"),
            ("zara-discord", "ZARA_DISCORD_TOKEN"),
            ("zara-github", "ZARA_GITHUB_TOKEN"),
            ("zara-knowledge", "BRAVE_SEARCH_API_KEY"),
            ("zara-starintel-server", "ZARA_STARINTEL_URL"),
            ("zara-starintel-server", "ZARA_STARINTEL_API_KEY"),
            ("zara-starintel-server", "ZARA_STARINTEL_API_KEY_FILE"),
            ("zara-starintel-server", "ZARA_STARINTEL_BOOTSTRAP_SECRET"),
            ("zara-starintel-server", "ZARA_STARINTEL_BOOTSTRAP_SECRET_FILE"),
        )
        for plugin_name, variable in cases:
            with self.subTest(plugin_name=plugin_name, variable=variable), mock.patch.dict(
                os.environ,
                {variable: "existing-secret"},
                clear=True,
            ):
                with fake_dependency_environment(plugin_name):
                    self.assertNotIn(variable, os.environ)
                self.assertEqual(os.environ.get(variable), "existing-secret")

    def test_fake_dependency_environment_does_not_strip_unrelated_credentials(self) -> None:
        variable = "UNRELATED_PROVIDER_TOKEN"
        with mock.patch.dict(os.environ, {variable: "existing-secret"}, clear=True):
            with fake_dependency_environment("zara-browser"):
                self.assertEqual(os.environ.get(variable), "existing-secret")

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
