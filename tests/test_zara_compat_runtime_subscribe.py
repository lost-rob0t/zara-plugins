from __future__ import annotations

import unittest

from scripts.zara_compat_runtime import CompatibilityRuntime


class CompatibilityRuntimeSubscribeTest(unittest.TestCase):
    def test_default_subscription_is_accepted(self) -> None:
        runtime = CompatibilityRuntime("example")
        self.assertFalse(runtime.subscribe().closed)

    def test_explicit_valid_queue_size_is_accepted(self) -> None:
        runtime = CompatibilityRuntime("example")
        self.assertFalse(runtime.subscribe(maxsize=64).closed)

    def test_boolean_queue_size_is_rejected(self) -> None:
        runtime = CompatibilityRuntime("example")
        with self.assertRaises(TypeError):
            runtime.subscribe(maxsize=True)

    def test_non_integer_queue_size_is_rejected(self) -> None:
        runtime = CompatibilityRuntime("example")
        with self.assertRaises(TypeError):
            runtime.subscribe(maxsize="64")

    def test_out_of_range_queue_size_is_rejected(self) -> None:
        runtime = CompatibilityRuntime("example")
        for value in (0, 4097):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    runtime.subscribe(maxsize=value)


if __name__ == "__main__":
    unittest.main()
