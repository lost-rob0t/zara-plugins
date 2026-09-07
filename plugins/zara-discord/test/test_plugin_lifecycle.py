import unittest
from unittest.mock import Mock, patch

from discord_test_support import install_zara_stubs


install_zara_stubs()

from zara_discord_service.config import ConfigError
from zara_discord_service.plugin import ZaraDiscordPlugin


class FakeRuntime:
    def __init__(self):
        self.subscriptions = []
        self.workers = []

    def subscribe(self, *, maxsize):
        subscription = Mock()
        self.subscriptions.append((maxsize, subscription))
        return subscription

    def start_worker(self, name, target):
        self.workers.append((name, target))


class ZaraDiscordPluginLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.runtime = FakeRuntime()
        self.plugin = ZaraDiscordPlugin()

    @patch("zara_discord_service.plugin.config_directory")
    @patch("zara_discord_service.plugin.load_token")
    def test_missing_credentials_fail_start_without_runtime_resources(
        self,
        load_token,
        config_directory,
    ):
        config_directory.return_value = "/tmp/zara-discord-test"
        load_token.side_effect = ConfigError("missing Discord token")

        with self.assertRaisesRegex(RuntimeError, "Discord integration unavailable"):
            self.plugin.start(self.runtime)

        self.assertEqual(self.runtime.subscriptions, [])
        self.assertEqual(self.runtime.workers, [])
        self.assertIsNone(self.plugin._bot)
        self.assertIsNone(self.plugin._subscription)

    @patch("zara_discord_service.plugin.DiscordClient")
    @patch("zara_discord_service.plugin.ConversationController")
    @patch("zara_discord_service.plugin.ModerationAudit")
    @patch("zara_discord_service.plugin.ModerationAcknowledgementStore")
    @patch("zara_discord_service.plugin.PolicyStore")
    @patch("zara_discord_service.plugin.load_token")
    @patch("zara_discord_service.plugin.config_directory")
    def test_client_setup_failure_does_not_leak_subscription_or_workers(
        self,
        config_directory,
        load_token,
        policy_store,
        acknowledgement_store,
        moderation_audit,
        conversation_controller,
        discord_client,
    ):
        del acknowledgement_store, moderation_audit, conversation_controller
        config_directory.return_value = "/tmp/zara-discord-test"
        load_token.return_value = "test-token-not-a-secret"
        policy_store.return_value.requires_message_content.return_value = False
        discord_client.side_effect = RuntimeError("synthetic client setup failure")

        with self.assertRaisesRegex(RuntimeError, "synthetic client setup failure"):
            self.plugin.start(self.runtime)

        self.assertEqual(self.runtime.subscriptions, [])
        self.assertEqual(self.runtime.workers, [])
        self.assertIsNone(self.plugin._bot)
        self.assertIsNone(self.plugin._subscription)


if __name__ == "__main__":
    unittest.main()
