import unittest
from types import SimpleNamespace

from discord_test_support import LIB_ROOT
from zara_discord_service.moderation_bot import ModeratedZaraDiscordBot


def permissions(**values):
    defaults = {
        "administrator": False,
        "manage_guild": False,
        "moderate_members": False,
        "kick_members": False,
        "ban_members": False,
        "manage_messages": False,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


class ModerationProtectionTests(unittest.TestCase):
    def reason(self, *, target_id=4, owner_id=99, bot=False, bot_user_id=100, **perms):
        fake_bot = SimpleNamespace(user=SimpleNamespace(id=bot_user_id))
        guild = SimpleNamespace(owner_id=owner_id)
        target = SimpleNamespace(
            id=target_id,
            bot=bot,
            guild_permissions=permissions(**perms),
        )
        return ModeratedZaraDiscordBot._protected_reason(fake_bot, guild, target)

    def test_guild_owner_is_protected(self):
        self.assertIn("guild owner", self.reason(target_id=99, owner_id=99))

    def test_bot_and_self_targets_are_protected(self):
        self.assertIn("bot/self", self.reason(target_id=100, bot_user_id=100))
        self.assertIn("bot target", self.reason(target_id=4, bot=True))

    def test_every_moderation_permission_is_protected(self):
        for name in (
            "administrator",
            "manage_guild",
            "moderate_members",
            "kick_members",
            "ban_members",
            "manage_messages",
        ):
            with self.subTest(permission=name):
                self.assertIn(name, self.reason(**{name: True}))

    def test_unprivileged_member_is_not_protected(self):
        self.assertEqual(self.reason(), "")


if __name__ == "__main__":
    unittest.main()
