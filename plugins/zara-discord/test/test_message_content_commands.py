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
class MessageContentCommandTests(unittest.TestCase):
    def test_enabling_random_mode_explains_privileged_intent_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = PolicyStore(Path(temporary))
            bot = ZaraDiscordBot(object(), store)
            command = bot.tree.get_command("random").get_command("on")
            interaction = SimpleNamespace(
                guild_id=10,
                guild=SimpleNamespace(owner_id=20),
                user=SimpleNamespace(id=20),
                permissions=discord.Permissions.none(),
                response=FakeResponse(),
            )

            asyncio.run(command.callback(interaction))

            self.assertTrue(store.policy(10).random_mode)
            message = interaction.response.messages[-1][0]
            self.assertIn("Restart Zara", message)
            self.assertIn("Developer Portal", message)


if __name__ == "__main__":
    unittest.main()
