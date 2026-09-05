import asyncio
import importlib.util
import tempfile
import unittest
from pathlib import Path

from discord_test_support import install_zara_stubs

install_zara_stubs()

DISCORD_AVAILABLE = importlib.util.find_spec("discord") is not None
if DISCORD_AVAILABLE:
    from zara_discord_service.bot import ZaraDiscordBot
    from zara_discord_service.config import PolicyStore


class FakeController:
    pass


@unittest.skipUnless(DISCORD_AVAILABLE, "discord.py is provided by the Nix plugin environment")
class GatewayLoopTests(unittest.TestCase):
    def test_setup_hook_captures_running_gateway_loop(self):
        with tempfile.TemporaryDirectory() as temporary:
            bot = ZaraDiscordBot(
                FakeController(),
                PolicyStore(Path(temporary)),
            )

            async def exercise():
                current = asyncio.get_running_loop()
                await bot.setup_hook()
                self.assertIs(bot._gateway_loop, current)

            asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
