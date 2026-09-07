import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_home.plugin import ZaraHomePlugin


class FakeProvider:
    def list_devices(self):
        return []


class FakeEventStream:
    def __init__(self):
        self.started = 0
        self.stopped = 0
        self.join_timeouts = []

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def join(self, timeout):
        self.join_timeouts.append(timeout)
        return True


class ZaraHomePluginLifecycleTests(unittest.TestCase):
    def test_plugin_owns_event_stream_start_stop_and_bounded_join(self):
        stream = FakeEventStream()
        plugin = ZaraHomePlugin(provider=FakeProvider(), event_stream=stream)

        plugin.start(runtime=None)
        plugin.stop()

        self.assertEqual(stream.started, 1)
        self.assertEqual(stream.stopped, 1)
        self.assertEqual(len(stream.join_timeouts), 1)
        self.assertGreater(stream.join_timeouts[0], 0)
        self.assertLessEqual(stream.join_timeouts[0], 60)

    def test_plugin_without_event_stream_keeps_rest_provider_usable(self):
        plugin = ZaraHomePlugin(provider=FakeProvider(), event_stream=None)

        plugin.start(runtime=None)
        plugin.stop()

        self.assertEqual(plugin.status(), '{"status": "ready"}')

    def test_registry_declares_production_websocket_client(self):
        registry = json.loads((REPO_ROOT / "plugins.json").read_text())
        entry = next(plugin for plugin in registry["plugins"] if plugin["name"] == "zara-home")

        self.assertIn("websocket-client", entry.get("python_dependencies", []))

    def test_production_websocket_module_imports(self):
        import websocket

        self.assertTrue(callable(websocket.create_connection))


if __name__ == "__main__":
    unittest.main()
