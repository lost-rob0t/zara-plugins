from __future__ import annotations

import unittest

from scripts.zara_compat_runtime import CompatibilityRuntime


def _worker(_stop_event) -> None:
    return None


class CompatibilityRuntimeWorkerTest(unittest.TestCase):
    def test_valid_worker_is_registered(self) -> None:
        runtime = CompatibilityRuntime("example")
        worker = runtime.start_worker("events", _worker)
        self.assertEqual(worker.name, "events")

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


if __name__ == "__main__":
    unittest.main()
