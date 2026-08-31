import unittest

from discord_test_support import LIB_ROOT
from zara_discord_service.routing import ResponseRouter, split_discord_message


class RoutingTests(unittest.TestCase):
    def test_split_preserves_text_within_platform_limit(self):
        text = "alpha " * 700
        chunks = split_discord_message(text, limit=2000)

        self.assertTrue(all(0 < len(chunk) <= 2000 for chunk in chunks))
        self.assertEqual("".join(chunks), text)

    def test_split_handles_long_unbroken_text_and_empty_response(self):
        self.assertEqual(
            split_discord_message("x" * 4001, limit=2000),
            ["x" * 2000, "x" * 2000, "x"],
        )
        self.assertEqual(split_discord_message(""), [])

    def test_router_delivers_registered_response(self):
        delivered = []
        router = ResponseRouter()

        router.register("turn-1", delivered.append)
        router.deliver("turn-1", "hello")

        self.assertEqual(delivered, ["hello"])
        self.assertEqual(router.pending_count, 0)

    def test_router_buffers_response_until_receipt_registration(self):
        delivered = []
        router = ResponseRouter()

        router.deliver("turn-1", "too fast")
        router.register("turn-1", delivered.append)

        self.assertEqual(delivered, ["too fast"])
        self.assertEqual(router.buffered_count, 0)

    def test_router_discards_failed_submission_and_bounds_early_responses(self):
        router = ResponseRouter(max_buffered=2)
        router.register("failed", lambda _text: None)
        router.discard("failed")
        router.deliver("turn-1", "one")
        router.deliver("turn-2", "two")
        router.deliver("turn-3", "three")

        self.assertEqual(router.pending_count, 0)
        self.assertEqual(router.buffered_turn_ids, ("turn-2", "turn-3"))


if __name__ == "__main__":
    unittest.main()
