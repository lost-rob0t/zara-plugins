import tempfile
import unittest
from pathlib import Path

from discord_test_support import install_zara_stubs

install_zara_stubs()

from zara_discord_service.config import PolicyStore


class RuntimeAccessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_discord_is_enabled_and_open_by_default(self):
        store = PolicyStore(self.directory)
        policy = store.policy(10)

        self.assertTrue(policy.enabled)
        self.assertEqual(policy.access_mode, "open")
        self.assertTrue(store.is_allowed(guild_id=10, user_id=20, channel_id=30))

    def test_disabling_discord_blocks_guild_requests_and_persists(self):
        store = PolicyStore(self.directory)
        store.set_enabled(10, False)

        self.assertFalse(store.is_allowed(guild_id=10, user_id=20, channel_id=30))
        reloaded = PolicyStore(self.directory)
        self.assertFalse(reloaded.policy(10).enabled)
        self.assertFalse(reloaded.is_allowed(guild_id=10, user_id=20, channel_id=30))

    def test_restricted_mode_only_allows_authorized_users(self):
        store = PolicyStore(self.directory)
        store.set_access_mode(10, "restricted")
        store.add_authorized_user(10, 20)

        self.assertTrue(store.is_allowed(guild_id=10, user_id=20, channel_id=30))
        self.assertFalse(store.is_allowed(guild_id=10, user_id=21, channel_id=30))


if __name__ == "__main__":
    unittest.main()
