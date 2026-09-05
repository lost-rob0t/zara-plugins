import unittest

from discord_test_support import LIB_ROOT
from zara_discord_service.moderation import ModerationContextStore
from zara_discord_service.moderation_tools import build_moderation_tools


class ModerationToolTests(unittest.TestCase):
    def setUp(self):
        self.store = ModerationContextStore()
        self.calls = []
        self.tools = {
            tool.name: tool
            for tool in build_moderation_tools(
                self.store,
                lambda action, context, reason, timeout_seconds: self.calls.append(
                    (action, context, reason, timeout_seconds)
                ) or f"{action}:ok",
            )
        }

    def issue(self):
        return self.store.issue(guild_id=1, channel_id=2, message_id=3, target_id=4)

    def test_surface_has_only_scoped_moderation_tools(self):
        self.assertEqual(
            set(self.tools),
            {
                "discord_moderation_inspect",
                "discord_moderation_delete",
                "discord_moderation_warn",
                "discord_moderation_timeout",
                "discord_moderation_kick",
                "discord_moderation_ban",
            },
        )

    def test_inspect_does_not_consume_context(self):
        token = self.issue()
        first = self.tools["discord_moderation_inspect"].invoke({"context_token": token})
        second = self.tools["discord_moderation_inspect"].invoke({"context_token": token})

        self.assertEqual(first, "inspect:ok")
        self.assertEqual(second, "inspect:ok")
        self.assertEqual(len(self.calls), 2)

    def test_mutation_consumes_context_before_execution(self):
        token = self.issue()
        result = self.tools["discord_moderation_kick"].invoke(
            {"context_token": token, "reason": "repeated spam"}
        )

        self.assertEqual(result, "kick:ok")
        with self.assertRaisesRegex(ValueError, "expired or unknown"):
            self.tools["discord_moderation_ban"].invoke(
                {"context_token": token, "reason": "try twice"}
            )

    def test_timeout_is_bounded(self):
        token = self.issue()
        with self.assertRaises(ValueError):
            self.tools["discord_moderation_timeout"].invoke(
                {"context_token": token, "timeout_seconds": 0, "reason": "nope"}
            )

    def test_reason_is_bounded_and_plain(self):
        token = self.issue()
        with self.assertRaises(ValueError):
            self.tools["discord_moderation_warn"].invoke(
                {"context_token": token, "reason": "x" * 501}
            )


if __name__ == "__main__":
    unittest.main()
