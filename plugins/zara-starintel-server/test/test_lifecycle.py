import unittest

from test_plugin import Runtime, ZaraStarIntelServerPlugin


class ZaraStarIntelServerLifecycleTest(unittest.TestCase):
    def test_start_and_stop_without_live_server(self):
        plugin = ZaraStarIntelServerPlugin()
        plugin.start(Runtime({"base_url": "https://starintel.example"}))
        plugin.stop()


if __name__ == "__main__":
    unittest.main()
