from __future__ import annotations

import unittest

from scripts.zara_compat_runtime import CompatibilityRuntime


class CompatibilityRuntimeWorkerIdentityTest(unittest.TestCase):
    def test_worker_name_matches_core_plugin_scoped_identity(self) -> None:
        runtime = CompatibilityRuntime("example-plugin")
        worker = runtime.start_worker("sync", lambda _stop_event: None)
        self.assertEqual(worker.name, "example-plugin-sync")


if __name__ == "__main__":
    unittest.main()
