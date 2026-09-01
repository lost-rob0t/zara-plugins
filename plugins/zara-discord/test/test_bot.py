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

    from zara_discord_service.bot import (
        ZaraDiscordBot,
        bare_mention_prompt,
        conversation_id,
        remove_bot_mention,
        spontaneous_reply_prompt,
    )
    from zara_discord_service.config import PolicyStore


class FakeController:
    def submit(self, **_kwargs):
        pass


class FakeResponse:
    def __init__(self):
        self.messages = []

    async def send_message(self, content, **kwargs):
        self.messages.append((content, kwargs))


@unittest.skipUnless(DISCORD_AVAILABLE, "discord.py is provided by the Nix plugin environment")
class BotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.bot = ZaraDiscordBot(FakeController(), PolicyStore(Path(self.temporary.name)))

    def tearDown(self):
        self.temporary.cleanup()

    def test_uses_non_privileged_message_intents(self):
        self.assertTrue(self.bot.intents.guilds)
        self.assertTrue(self.bot.intents.messages)
        self.assertFalse(self.bot.intents.message_content)

    def test_registers_talk_setup_and_random_slash_commands(self):
        root = self.bot.tree.get_command("zara")
        random_group = self.bot.tree.get_command("random")

        self.assertIsNotNone(root)
        self.assertIsNotNone(random_group)
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
        self.assertEqual(
            {command.name for command in random_group.commands},
            {"on", "off", "chance"},
        )

    def test_setup_commands_require_manage_server(self):
        root = self.bot.tree.get_command("zara")
        random_group = self.bot.tree.get_command("random")

        for group_name in ("access", "users", "channels"):
            for command in root.get_command(group_name).commands:
                self.assertTrue(command.default_permissions.manage_guild)
                self.assertTrue(command.guild_only)
        self.assertTrue(root.get_command("status").default_permissions.manage_guild)
        for command in random_group.commands:
            self.assertTrue(command.default_permissions.manage_guild)
            self.assertTrue(command.guild_only)

    def test_manager_check_uses_interaction_permissions(self):
        interaction = SimpleNamespace(
            guild_id=10,
            guild=SimpleNamespace(owner_id=99),
            user=SimpleNamespace(id=20),
            permissions=discord.Permissions(manage_guild=True),
            response=FakeResponse(),
        )

        self.assertTrue(asyncio.run(self.bot._require_manager(interaction)))
        self.assertEqual(interaction.response.messages, [])

    def test_manager_check_accepts_administrator(self):
        interaction = SimpleNamespace(
            guild_id=10,
            guild=SimpleNamespace(owner_id=99),
            user=SimpleNamespace(id=20),
            permissions=discord.Permissions(administrator=True),
            response=FakeResponse(),
        )

        self.assertTrue(asyncio.run(self.bot._require_manager(interaction)))

    def test_manager_check_accepts_guild_owner(self):
        interaction = SimpleNamespace(
            guild_id=10,
            guild=SimpleNamespace(owner_id=20),
            user=SimpleNamespace(id=20),
            permissions=discord.Permissions.none(),
            response=FakeResponse(),
        )

        self.assertTrue(asyncio.run(self.bot._require_manager(interaction)))

    def test_manager_check_rejects_member_without_permission(self):
        interaction = SimpleNamespace(
            guild_id=10,
            guild=SimpleNamespace(owner_id=99),
            user=SimpleNamespace(id=20),
            permissions=discord.Permissions.none(),
            response=FakeResponse(),
        )

        self.assertFalse(asyncio.run(self.bot._require_manager(interaction)))
        self.assertIn("Manage Server permission", interaction.response.messages[0][0])

    def test_removes_both_discord_mention_forms(self):
        self.assertEqual(remove_bot_mention("<@42> hello", 42), "hello")
        self.assertEqual(remove_bot_mention("hello <@!42>", 42), "hello")
        self.assertEqual(remove_bot_mention("<@43> keep this", 42), "<@43> keep this")

    def test_bare_mention_generates_natural_prompt(self):
        prompt = bare_mention_prompt("Mina")

        self.assertIn("Mina", prompt)
        self.assertIn("pinged you", prompt)

    def test_spontaneous_prompt_works_without_message_content_intent(self):
        prompt = spontaneous_reply_prompt("Mina", "")

        self.assertIn("Mina", prompt)
        self.assertIn("Spontaneously", prompt)

    def test_spontaneous_prompt_uses_content_when_available(self):
        prompt = spontaneous_reply_prompt("Mina", "hello there")

        self.assertIn("hello there", prompt)

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
