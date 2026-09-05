import importlib.util
import unittest

from discord_test_support import install_zara_stubs

install_zara_stubs()

DISCORD_AVAILABLE = importlib.util.find_spec("discord") is not None
if DISCORD_AVAILABLE:
    from zara_discord_service.bot import conversation_id


@unittest.skipUnless(DISCORD_AVAILABLE, "discord.py is provided by the Nix plugin environment")
class ConversationIsolationTest(unittest.TestCase):
    def test_guild_conversation_id_includes_numeric_user_id(self):
        first = conversation_id(guild_id=10, channel_id=30, user_id=20)
        second = conversation_id(guild_id=10, channel_id=30, user_id=21)

        self.assertEqual(first, "discord:guild:10:channel:30:user:20")
        self.assertEqual(second, "discord:guild:10:channel:30:user:21")
        self.assertNotEqual(first, second)

    def test_dm_conversation_id_includes_numeric_user_id(self):
        first = conversation_id(guild_id=None, channel_id=30, user_id=20)
        second = conversation_id(guild_id=None, channel_id=30, user_id=21)

        self.assertEqual(first, "discord:dm:channel:30:user:20")
        self.assertEqual(second, "discord:dm:channel:30:user:21")
        self.assertNotEqual(first, second)

    def test_conversation_id_rejects_non_integer_identifiers(self):
        with self.assertRaises(TypeError):
            conversation_id(guild_id=10, channel_id=30, user_id="Mina")

        with self.assertRaises(TypeError):
            conversation_id(guild_id="guild", channel_id=30, user_id=20)


if __name__ == "__main__":
    unittest.main()
