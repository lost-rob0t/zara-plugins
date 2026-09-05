import json
import os
import tempfile
import unittest
from pathlib import Path

from discord_test_support import LIB_ROOT
from zara_discord_service.moderation_acknowledgements import (
    AcknowledgementConfigError,
    ModerationAcknowledgementStore,
)


class ModerationAcknowledgementTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.store = ModerationAcknowledgementStore(self.directory)

    def tearDown(self):
        self.temporary.cleanup()

    def test_guild_acknowledgement_round_trips(self):
        self.store.set_moderation_acknowledgement(
            10,
            "warn",
            "uwu, moderation bonk deployed",
        )

        reloaded = ModerationAcknowledgementStore(self.directory)
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

    def test_policy_file_is_private_and_contains_only_configured_text(self):
        self.store.set_moderation_acknowledgement(10, "warn", "bonk deployed")

        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)
        payload = json.loads(self.store.path.read_text(encoding="utf-8"))
        self.assertEqual(
            payload,
            {
                "version": 1,
                "guilds": {
                    "10": {
                        "acknowledgements": {"warn": "bonk deployed"},
                        "channels": {},
                    }
                },
            },
        )

    def test_invalid_on_disk_mentions_fail_closed(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.directory.joinpath("moderation-acknowledgements.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "guilds": {
                        "10": {
                            "acknowledgements": {"warn": "ping @everyone"},
                            "channels": {},
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(AcknowledgementConfigError, "invalid Discord"):
            ModerationAcknowledgementStore(self.directory)

    def test_negative_discord_ids_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "guild_id must be non-negative"):
            self.store.set_moderation_acknowledgement(-1, "warn", "bonk")
        with self.assertRaisesRegex(ValueError, "channel_id must be non-negative"):
            self.store.set_channel_moderation_acknowledgement(10, -1, "warn", "bonk")


if __name__ == "__main__":
    unittest.main()
