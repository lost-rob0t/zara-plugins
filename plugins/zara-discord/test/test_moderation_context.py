import unittest

from discord_test_support import LIB_ROOT
from zara_discord_service.moderation import ModerationContextStore


class Clock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


class TokenFactory:
    def __init__(self):
        self.calls = []
        self.counter = 0

    def __call__(self, size):
        self.calls.append(size)
        self.counter += 1
        return f"opaque-capability-token-{self.counter:08d}"


class ModerationContextStoreTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.tokens = TokenFactory()
        self.store = ModerationContextStore(
            ttl_seconds=30.0,
            max_contexts=2,
            clock=self.clock,
            token_factory=self.tokens,
        )

    def test_token_is_opaque_and_scope_is_kept_server_side(self):
        token = self.store.issue(
            guild_id=1,
            channel_id=2,
            message_id=3,
            target_id=4,
        )

        context = self.store.resolve(token)
        self.assertEqual(token, "opaque-capability-token-00000001")
        self.assertEqual(self.tokens.calls, [32])
        self.assertEqual(context.guild_id, 1)
        self.assertEqual(context.channel_id, 2)
        self.assertEqual(context.message_id, 3)
        self.assertEqual(context.target_id, 4)

    def test_token_expires_fail_closed(self):
        token = self.store.issue(guild_id=1, channel_id=2, message_id=3, target_id=4)
        self.clock.value += 31.0

        with self.assertRaisesRegex(ValueError, "expired or unknown"):
            self.store.resolve(token)

    def test_token_is_single_use_after_consumption(self):
        token = self.store.issue(guild_id=1, channel_id=2, message_id=3, target_id=4)

        context = self.store.consume(token)
        self.assertEqual(context.message_id, 3)
        with self.assertRaisesRegex(ValueError, "expired or unknown"):
            self.store.consume(token)

    def test_capacity_evicts_oldest_context(self):
        first = self.store.issue(guild_id=1, channel_id=2, message_id=3, target_id=4)
        second = self.store.issue(guild_id=1, channel_id=2, message_id=5, target_id=6)
        third = self.store.issue(guild_id=1, channel_id=2, message_id=7, target_id=8)

        with self.assertRaisesRegex(ValueError, "expired or unknown"):
            self.store.resolve(first)
        self.assertEqual(self.store.resolve(second).message_id, 5)
        self.assertEqual(self.store.resolve(third).message_id, 7)

    def test_invalid_ids_and_bounds_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "guild_id"):
            self.store.issue(guild_id=-1, channel_id=2, message_id=3, target_id=4)
        with self.assertRaisesRegex(ValueError, "ttl_seconds"):
            ModerationContextStore(ttl_seconds=0)
        with self.assertRaisesRegex(ValueError, "max_contexts"):
            ModerationContextStore(max_contexts=0)

    def test_invalid_token_source_fails_closed(self):
        store = ModerationContextStore(token_factory=lambda _size: "short")
        with self.assertRaisesRegex(ValueError, "token source"):
            store.issue(guild_id=1, channel_id=2, message_id=3, target_id=4)


if __name__ == "__main__":
    unittest.main()
