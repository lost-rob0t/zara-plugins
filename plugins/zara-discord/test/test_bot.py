import importlib.util
import tempfile
import unittest
from pathlib import Path

from discord_test_support import install_zara_stubs

install_zara_stubs()

DISCORD_AVAILABLE = importlib.util.find_spec("discord") is not None
if DISCORD_AVAILABLE:
    from zara_discord_service.bot import ZaraDiscordBot, conversation_id, remove_bot_mention
    from zara_discord_service.config import PolicyStore


class FakeController:
    def submit(self, **_kwargs):
        pass


@unittest.skipUnless(DISCORD_AVAILABLE, "discord.py is provided by the Nix plugin environment")
class BotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.bot = ZaraDiscordBot(FakeController(), PolicyStore(Path(self.temporary.name)))

    def tearDown(self):
        self.temporary.cleanup()

    def test_uses_non_privileged_mention_and_dm_message_intents(self):
        self.assertTrue(self.bot.intents.guilds)
        self.assertTrue(self.bot.intents.messages)
        self.assertFalse(self.bot.intents.message_content)

    def test_registers_talk_and_all_setup_slash_commands(self):
        root = self.bot.tree.get_command("zara")

        self.assertIsNotNone(root)
        self.assertEqual(
            {command.name for command in root.commands},
            {"ask", "status", "access", "users", "channels"},
        )
        self.assertEqual(
            {command.name for command in root.get_command("access").commands},
            {"set"},
        )
        self.assertEqual(
            {command.name for command in root.get_command("users").commands},
            {"add", "remove", "clear"},
        )
        self.assertEqual(
            {command.name for command in root.get_command("channels").commands},
            {"add", "remove", "clear"},
        )

    def test_setup_commands_require_manage_server(self):
        root = self.bot.tree.get_command("zara")

        for group_name in ("access", "users", "channels"):
            for command in root.get_command(group_name).commands:
                self.assertTrue(command.default_permissions.manage_guild)
                self.assertTrue(command.guild_only)
        self.assertTrue(root.get_command("status").default_permissions.manage_guild)

    def test_removes_both_discord_mention_forms(self):
        self.assertEqual(remove_bot_mention("<@42> hello", 42), "hello")
        self.assertEqual(remove_bot_mention("hello <@!42>", 42), "hello")
        self.assertEqual(remove_bot_mention("<@43> keep this", 42), "<@43> keep this")

    def test_conversation_ids_are_stable_per_channel(self):
        self.assertEqual(
            conversation_id(guild_id=10, channel_id=30),
            "discord:guild:10:channel:30",
        )
        self.assertEqual(
            conversation_id(guild_id=None, channel_id=30),
            "discord:dm:channel:30",
        )


if __name__ == "__main__":
    unittest.main()
