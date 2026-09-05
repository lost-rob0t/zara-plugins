import asyncio
import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from discord_test_support import install_zara_stubs

install_zara_stubs()

DISCORD_AVAILABLE = importlib.util.find_spec("discord") is not None
if DISCORD_AVAILABLE:
    import discord

    from zara_discord_service.bot import ZaraDiscordBot
    from zara_discord_service.config import PolicyStore


class FakeResponse:
    def __init__(self):
        self.messages = []

    async def send_message(self, content, **kwargs):
        self.messages.append((content, kwargs))


@unittest.skipUnless(DISCORD_AVAILABLE, "discord.py is provided by the Nix plugin environment")
class ChannelInspectionCommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = PolicyStore(Path(self.temporary.name))
        self.bot = ZaraDiscordBot(object(), self.store)

    def tearDown(self):
        self.temporary.cleanup()

    def _interaction(self, channel_id=30):
        return SimpleNamespace(
            guild_id=10,
            channel_id=channel_id,
            guild=SimpleNamespace(owner_id=20),
            user=SimpleNamespace(id=20),
            permissions=discord.Permissions.none(),
            response=FakeResponse(),
        )

    def test_random_channel_set_configures_current_channel(self):
        channel_group = self.bot.tree.get_command("random").get_command("channel")
        command = channel_group.get_command("set")
        interaction = self._interaction()

        asyncio.run(
            command.callback(
                interaction,
                True,
                25.0,
                "Only build failures",
                "One sentence",
                False,
                None,
            )
        )

        policy = self.store.inspection_policy(10, 30)
        self.assertTrue(policy.enabled)
        self.assertEqual(policy.chance, 0.25)
        self.assertEqual(policy.trigger_prompt, "Only build failures")
        self.assertEqual(policy.response_style_prompt, "One sentence")
        self.assertFalse(policy.moderation_enabled)
        self.assertIn("Restart Zara", interaction.response.messages[-1][0])

    def test_random_channel_set_can_target_selected_channel(self):
        channel_group = self.bot.tree.get_command("random").get_command("channel")
        command = channel_group.get_command("set")
        interaction = self._interaction(channel_id=30)
        selected = SimpleNamespace(id=31)

        asyncio.run(
            command.callback(
                interaction,
                False,
                5.0,
                "",
                "",
                True,
                selected,
            )
        )

        policy = self.store.inspection_policy(10, 31)
        self.assertFalse(policy.enabled)
        self.assertTrue(policy.moderation_enabled)


if __name__ == "__main__":
    unittest.main()
