import tempfile
import unittest
from pathlib import Path

from discord_test_support import install_zara_stubs

install_zara_stubs()

from zara_discord_service.config import PolicyStore


class ChannelInspectionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.store = PolicyStore(self.directory)

    def tearDown(self):
        self.temporary.cleanup()

    def test_channel_without_override_inherits_guild_inspection_defaults(self):
        self.store.set_random_mode(10, True)
        self.store.set_random_reply_chance(10, 0.25)
        self.store.set_inspection_trigger_prompt(10, "Reply only to build failures")
        self.store.set_response_style_prompt(10, "Keep it terse")
        self.store.set_moderation_enabled(10, True)

        policy = self.store.inspection_policy(10, 30)

        self.assertTrue(policy.enabled)
        self.assertEqual(policy.chance, 0.25)
        self.assertEqual(policy.trigger_prompt, "Reply only to build failures")
        self.assertEqual(policy.response_style_prompt, "Keep it terse")
        self.assertTrue(policy.moderation_enabled)

    def test_channel_override_replaces_every_inspection_field(self):
        self.store.set_random_mode(10, True)
        self.store.set_random_reply_chance(10, 0.25)
        self.store.set_channel_inspection_policy(
            10,
            30,
            enabled=False,
            chance=0.75,
            trigger_prompt="Only CI failures",
            response_style_prompt="One sentence",
            moderation_enabled=True,
        )

        policy = self.store.inspection_policy(10, 30)

        self.assertFalse(policy.enabled)
        self.assertEqual(policy.chance, 0.75)
        self.assertEqual(policy.trigger_prompt, "Only CI failures")
        self.assertEqual(policy.response_style_prompt, "One sentence")
        self.assertTrue(policy.moderation_enabled)

    def test_channel_override_persists_and_can_enable_message_content(self):
        self.store.set_channel_inspection_policy(
            10,
            30,
            enabled=True,
            chance=0.5,
            trigger_prompt="Interesting messages",
            response_style_prompt="Dry",
            moderation_enabled=False,
        )

        reloaded = PolicyStore(self.directory)
        policy = reloaded.inspection_policy(10, 30)

        self.assertTrue(policy.enabled)
        self.assertEqual(policy.chance, 0.5)
        self.assertTrue(reloaded.requires_message_content())

    def test_channel_chance_rejects_out_of_range_values(self):
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            self.store.set_channel_inspection_policy(
                10,
                30,
                enabled=True,
                chance=1.1,
                trigger_prompt="",
                response_style_prompt="",
                moderation_enabled=False,
            )


if __name__ == "__main__":
    unittest.main()
