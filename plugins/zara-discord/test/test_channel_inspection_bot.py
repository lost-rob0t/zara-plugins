import asyncio
import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from discord_test_support import install_zara_stubs

install_zara_stubs()

DISCORD_AVAILABLE = importlib.util.find_spec("discord") is not None
if DISCORD_AVAILABLE:
    from zara_discord_service.bot import ZaraDiscordBot
    from zara_discord_service.config import PolicyStore


class FakeController:
    def __init__(self):
        self.calls = []

    def submit(self, **kwargs):
        self.calls.append(kwargs)


@unittest.skipUnless(DISCORD_AVAILABLE, "discord.py is provided by the Nix plugin environment")
class ChannelInspectionBotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = PolicyStore(Path(self.temporary.name))
        self.controller = FakeController()
        self.bot = ZaraDiscordBot(self.controller, self.store)
        self.bot._connection.user = SimpleNamespace(id=42)

    def tearDown(self):
        self.temporary.cleanup()

    def _message(self, channel_id):
        return SimpleNamespace(
            author=SimpleNamespace(bot=False, id=20, name="Mina", display_name="Mina"),
            guild=SimpleNamespace(id=10),
            mentions=[],
            channel=SimpleNamespace(id=channel_id, parent_id=None),
            content="build failed",
        )

    def test_channel_can_enable_inspection_when_guild_default_is_off(self):
        self.store.set_channel_inspection_policy(
            10,
            30,
            enabled=True,
            chance=1.0,
            trigger_prompt="Inspect failures",
            response_style_prompt="Brief",
            moderation_enabled=False,
        )

        with mock.patch("zara_discord_service.bot.random.random", return_value=0.0):
            asyncio.run(self.bot.on_message(self._message(30)))
            asyncio.run(self.bot.on_message(self._message(31)))

        self.assertEqual(len(self.controller.calls), 1)
        self.assertIn("Inspect failures", self.controller.calls[0]["text"])
        self.assertIn("Brief", self.controller.calls[0]["text"])

    def test_channel_can_disable_inspection_when_guild_default_is_on(self):
        self.store.set_random_mode(10, True)
        self.store.set_channel_inspection_policy(
            10,
            30,
            enabled=False,
            chance=1.0,
            trigger_prompt="",
            response_style_prompt="",
            moderation_enabled=False,
        )

        with mock.patch("zara_discord_service.bot.random.random", return_value=0.0):
            asyncio.run(self.bot.on_message(self._message(30)))

        self.assertEqual(self.controller.calls, [])


if __name__ == "__main__":
    unittest.main()
