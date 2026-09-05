import tempfile
import unittest
from pathlib import Path

from discord_test_support import LIB_ROOT
from zara_discord_service.config import PolicyStore


class ModerationAcknowledgementTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.store = PolicyStore(self.directory)

    def tearDown(self):
        self.temporary.cleanup()

    def test_guild_acknowledgement_round_trips(self):
        self.store.set_moderation_acknowledgement(
            10,
            "warn",
            "uwu, moderation bonk deployed",
        )

        reloaded = PolicyStore(self.directory)
        self.assertEqual(
            reloaded.moderation_acknowledgement(10, 20, "warn"),
            "uwu, moderation bonk deployed",
        )

    def test_channel_acknowledgement_overrides_guild(self):
        self.store.set_moderation_acknowledgement(10, "ban", "guild bonk")
        self.store.set_channel_moderation_acknowledgement(
            10,
            20,
            "ban",
            "channel bonk",
        )

        self.assertEqual(
            self.store.moderation_acknowledgement(10, 20, "ban"),
            "channel bonk",
        )
        self.assertEqual(
            self.store.moderation_acknowledgement(10, 21, "ban"),
            "guild bonk",
        )

    def test_empty_channel_acknowledgement_clears_override(self):
        self.store.set_moderation_acknowledgement(10, "kick", "guild bonk")
        self.store.set_channel_moderation_acknowledgement(10, 20, "kick", "channel bonk")
        self.store.set_channel_moderation_acknowledgement(10, 20, "kick", "")

        self.assertEqual(
            self.store.moderation_acknowledgement(10, 20, "kick"),
            "guild bonk",
        )

    def test_acknowledgements_are_bounded_plain_text_and_mention_safe(self):
        invalid = (
            "x" * 161,
            "line one\nline two",
            "ping @everyone",
            "ping @here",
            "ping <@123>",
            "role <@&123>",
        )
        for value in invalid:
            with self.subTest(value=value[:20]):
                with self.assertRaises(ValueError):
                    self.store.set_moderation_acknowledgement(10, "warn", value)

    def test_only_supported_moderation_actions_are_configurable(self):
        with self.assertRaisesRegex(ValueError, "warn, timeout, kick, or ban"):
            self.store.set_moderation_acknowledgement(10, "delete", "nope")

    def test_unconfigured_action_has_no_public_acknowledgement(self):
        self.assertEqual(
            self.store.moderation_acknowledgement(10, 20, "timeout"),
            "",
        )


if __name__ == "__main__":
    unittest.main()
