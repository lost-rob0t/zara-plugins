import importlib.util
import os
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from discord_test_support import ServicePlugin, install_zara_stubs

install_zara_stubs()

DISCORD_AVAILABLE = importlib.util.find_spec("discord") is not None
if DISCORD_AVAILABLE:
    import zara_discord_service.plugin as plugin_module


class FakeSubscription:
    def close(self):
        pass

    def get(self, timeout):
        raise queue.Empty


class FakeRuntime:
    def __init__(self):
        self.workers = []
        self.subscription = FakeSubscription()

    def subscribe(self, *, maxsize):
        if maxsize != 128:
            raise AssertionError(maxsize)
        return self.subscription

    def start_worker(self, name, target):
        self.workers.append((name, target))


class FakeDiscordClient:
    instances = []

    def __init__(self, controller, policies):
        self.controller = controller
        self.policies = policies
        self.run_tokens = []
        self.close_requested = False
        self.instances.append(self)

    def run_gateway(self, token, stop_event):
        self.run_tokens.append(token)

    def request_close(self):
        self.close_requested = True


@unittest.skipUnless(DISCORD_AVAILABLE, "discord.py is provided by the Nix plugin environment")
class PluginTests(unittest.TestCase):
    def setUp(self):
        FakeDiscordClient.instances.clear()
        self.temporary = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temporary.cleanup()

    def test_factory_returns_service_plugin_with_stable_metadata(self):
        plugin = plugin_module.create_plugin()

        self.assertIsInstance(plugin, ServicePlugin)
        self.assertEqual(plugin.metadata.name, "zara-discord")
        self.assertEqual(plugin.metadata.version, "0.2.1")
        self.assertEqual(plugin.metadata.api_version, "1")

    def test_starts_bounded_workers_and_stops_gateway(self):
        environment = {
            "XDG_CONFIG_HOME": self.temporary.name,
            "ZARA_DISCORD_TOKEN": "test-token",
        }
        with mock.patch.dict(os.environ, environment, clear=True), mock.patch.object(
            plugin_module,
            "DiscordClient",
            FakeDiscordClient,
        ):
            runtime = FakeRuntime()
            plugin = plugin_module.create_plugin()
            plugin.start(runtime)

            self.assertEqual(
                [name for name, _target in runtime.workers],
                ["runtime-events", "gateway"],
            )
            gateway = FakeDiscordClient.instances[-1]
            runtime.workers[1][1](threading.Event())
            self.assertEqual(gateway.run_tokens, ["test-token"])

            plugin.stop()
            self.assertTrue(gateway.close_requested)


if __name__ == "__main__":
    unittest.main()
