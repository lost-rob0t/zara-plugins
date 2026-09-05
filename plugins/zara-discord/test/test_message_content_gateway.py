import importlib.util
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from discord_test_support import install_zara_stubs

install_zara_stubs()

DISCORD_AVAILABLE = importlib.util.find_spec("discord") is not None
if DISCORD_AVAILABLE:
    import discord

    from zara_discord_service.bot import ZaraDiscordBot
    from zara_discord_service.config import PolicyStore


@unittest.skipUnless(DISCORD_AVAILABLE, "discord.py is provided by the Nix plugin environment")
class MessageContentGatewayTests(unittest.TestCase):
    def test_privileged_intent_rejection_has_operator_recovery_instructions(self):
        with tempfile.TemporaryDirectory() as temporary:
            bot = ZaraDiscordBot(
                mock.Mock(),
                PolicyStore(Path(temporary)),
                message_content=True,
            )
            failure = discord.PrivilegedIntentsRequired(None)
            with mock.patch.object(bot, "run", side_effect=failure):
                with self.assertRaisesRegex(RuntimeError, "Developer Portal"):
                    bot.run_gateway("token", threading.Event())


if __name__ == "__main__":
    unittest.main()
