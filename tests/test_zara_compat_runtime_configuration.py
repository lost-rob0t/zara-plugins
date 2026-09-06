from __future__ import annotations

import unittest

from scripts.zara_compat_runtime import CompatibilityRuntime


class CompatibilityRuntimeConfigurationTest(unittest.TestCase):
    def test_configuration_is_read_only_like_zara_runtime(self) -> None:
        runtime = CompatibilityRuntime("example")
        with self.assertRaises(TypeError):
            runtime.configuration["enabled"] = True


if __name__ == "__main__":
    unittest.main()
