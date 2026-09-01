import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from discord_test_support import LIB_ROOT
from zara_discord_service.config import (
    DEFAULT_RANDOM_REPLY_CHANCE,
    ConfigError,
    PolicyStore,
    config_directory,
    load_token,
)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_config_directory_uses_zara_xdg_plugin_namespace(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.directory)}):
            self.assertEqual(
                config_directory(),
                self.directory / "zarathushtra" / "plugins" / "zara-discord",
            )

    def test_missing_policy_allows_every_user_and_channel(self):
        store = PolicyStore(self.directory)

        self.assertTrue(store.is_allowed(guild_id=10, user_id=20, channel_id=30))
        self.assertEqual(store.policy(10).access_mode, "open")
        self.assertEqual(store.policy(10).authorized_user_ids, frozenset())
        self.assertEqual(store.policy(10).allowed_channel_ids, frozenset())
        self.assertFalse(store.policy(10).random_mode)
        self.assertEqual(store.policy(10).random_reply_chance, DEFAULT_RANDOM_REPLY_CHANCE)

    def test_restricted_policy_requires_authorized_user_and_allowed_channel(self):
        store = PolicyStore(self.directory)
        store.set_access_mode(10, "restricted")
        store.add_authorized_user(10, 20)
        store.add_allowed_channel(10, 30)

        self.assertTrue(store.is_allowed(guild_id=10, user_id=20, channel_id=30))
        self.assertFalse(store.is_allowed(guild_id=10, user_id=21, channel_id=30))
        self.assertFalse(store.is_allowed(guild_id=10, user_id=20, channel_id=31))
        self.assertTrue(
            store.is_allowed(
                guild_id=10,
                user_id=20,
                channel_id=31,
                parent_channel_id=30,
            )
        )

    def test_channel_allowlist_is_enforced_in_open_mode(self):
        store = PolicyStore(self.directory)
        store.add_allowed_channel(10, 30)

        self.assertTrue(store.is_allowed(guild_id=10, user_id=999, channel_id=30))
        self.assertFalse(store.is_allowed(guild_id=10, user_id=999, channel_id=31))

    def test_direct_messages_remain_allowed(self):
        store = PolicyStore(self.directory)

        self.assertTrue(store.is_allowed(guild_id=None, user_id=20, channel_id=30))

    def test_restricted_policy_cannot_be_bypassed_through_direct_messages(self):
        store = PolicyStore(self.directory)
        store.set_access_mode(10, "restricted")
        store.add_authorized_user(10, 20)

        self.assertTrue(store.is_allowed(guild_id=None, user_id=20, channel_id=30))
        self.assertFalse(store.is_allowed(guild_id=None, user_id=21, channel_id=30))

    def test_policy_changes_persist_and_clear_back_to_allow_all(self):
        store = PolicyStore(self.directory)
        store.set_access_mode(10, "restricted")
        store.add_authorized_user(10, 20)
        store.add_allowed_channel(10, 30)
        store.set_random_mode(10, True)
        store.set_random_reply_chance(10, 0.25)

        reloaded = PolicyStore(self.directory)
        self.assertEqual(reloaded.policy(10).authorized_user_ids, frozenset({20}))
        self.assertEqual(reloaded.policy(10).allowed_channel_ids, frozenset({30}))
        self.assertTrue(reloaded.policy(10).random_mode)
        self.assertEqual(reloaded.policy(10).random_reply_chance, 0.25)
        self.assertTrue(reloaded.remove_authorized_user(10, 20))
        self.assertFalse(reloaded.remove_authorized_user(10, 20))
        self.assertTrue(reloaded.clear_allowed_channels(10))
        self.assertFalse(reloaded.clear_allowed_channels(10))

    def test_random_reply_chance_must_be_between_zero_and_one(self):
        store = PolicyStore(self.directory)

        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            store.set_random_reply_chance(10, -0.01)
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            store.set_random_reply_chance(10, 1.01)

    def test_old_settings_without_random_fields_load_with_defaults(self):
        self.directory.joinpath("settings.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "guilds": {
                        "10": {
                            "access_mode": "open",
                            "authorized_user_ids": [],
                            "allowed_channel_ids": [],
                        }
                    },
                }
            )
        )

        policy = PolicyStore(self.directory).policy(10)
        self.assertFalse(policy.random_mode)
        self.assertEqual(policy.random_reply_chance, DEFAULT_RANDOM_REPLY_CHANCE)

    def test_policy_file_is_private_and_contains_no_token(self):
        store = PolicyStore(self.directory)
        store.add_authorized_user(10, 20)

        self.assertEqual(self.directory.joinpath("settings.json").stat().st_mode & 0o777, 0o600)
        self.assertNotIn("token", self.directory.joinpath("settings.json").read_text().lower())

    def test_invalid_access_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "open or restricted"):
            PolicyStore(self.directory).set_access_mode(10, "private")

    def test_invalid_settings_fail_with_actionable_error(self):
        self.directory.joinpath("settings.json").write_text(json.dumps({"version": 2}))

        with self.assertRaisesRegex(ConfigError, "unsupported settings version"):
            PolicyStore(self.directory)

    def test_environment_token_has_priority(self):
        self.directory.joinpath("token").write_text("file-token\n")
        with mock.patch.dict(os.environ, {"ZARA_DISCORD_TOKEN": " environment-token "}):
            self.assertEqual(load_token(self.directory), "environment-token")

    def test_token_file_must_be_private(self):
        token_path = self.directory / "token"
        token_path.write_text("secret\n")
        os.chmod(token_path, 0o644)
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ConfigError, "chmod 600"):
                load_token(self.directory)
            os.chmod(token_path, 0o600)
            self.assertEqual(load_token(self.directory), "secret")

    def test_missing_token_has_bootstrap_instructions(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ConfigError, "ZARA_DISCORD_TOKEN"):
                load_token(self.directory)


if __name__ == "__main__":
    unittest.main()
