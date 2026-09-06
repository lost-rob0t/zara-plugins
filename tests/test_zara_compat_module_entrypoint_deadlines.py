from __future__ import annotations

import time
import unittest

from scripts.zara_compat import require_legacy_tool_entrypoint


class BlockingModule:
    def __getattr__(self, name):
        if name in {"register_tools", "register_skills"}:
            time.sleep(1.0)
            return lambda runtime: ()
        raise AttributeError(name)


class ZaraCompatibilityModuleEntrypointDeadlineTest(unittest.TestCase):
    def test_legacy_entrypoint_lookup_is_bounded(self) -> None:
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            require_legacy_tool_entrypoint(
                "zara-example",
                BlockingModule(),
                object,
                {},
                timeout=0.05,
            )
        self.assertLess(time.monotonic() - started, 0.5)


if __name__ == "__main__":
    unittest.main()
