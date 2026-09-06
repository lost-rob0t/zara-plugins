from __future__ import annotations

import unittest

from scripts.zara_compat import collect_service_tools


class AsyncServiceToolsCompatibilityTest(unittest.TestCase):
    def test_async_tools_are_collected(self) -> None:
        class Service:
            async def tools(self):
                return ["tool-a", "tool-b"]

        self.assertEqual(collect_service_tools(Service()), ("tool-a", "tool-b"))

    def test_sync_tools_remain_supported(self) -> None:
        class Service:
            def tools(self):
                return ["tool-a"]

        self.assertEqual(collect_service_tools(Service()), ("tool-a",))


if __name__ == "__main__":
    unittest.main()
