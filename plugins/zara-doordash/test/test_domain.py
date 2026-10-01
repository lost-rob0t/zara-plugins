import sys
import unittest
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_doordash.domain import DoorDashDomain, DoorDashError


class DoorDashDomainTests(unittest.TestCase):
    def test_prepare_builds_bounded_consumer_search_handoff(self):
        result = DoorDashDomain().prepare(
            item="spicy chicken sandwich",
            merchant="Wendys",
            modifiers=["no mayo", "large fries"],
            context={"daypart": "late_night"},
        )
        self.assertEqual(result["provider"], "doordash")
        self.assertEqual(result["status"], "handoff_ready")
        self.assertFalse(result["purchase_completed"])
        self.assertTrue(result["user_confirmation_required"])
        self.assertIn("doordash.com", urlparse(result["url"]).netloc)
        decoded = unquote(result["url"])
        self.assertIn("Wendys", decoded)
        self.assertIn("spicy chicken sandwich", decoded)

    def test_prepare_does_not_claim_cart_or_payment_state(self):
        result = DoorDashDomain().prepare(item="tacos")
        self.assertNotIn("order_id", result)
        self.assertNotIn("payment", result)
        self.assertEqual(result["checkout_mode"], "consumer_handoff")

    def test_preference_observation_is_generic_and_context_preserving(self):
        observation = DoorDashDomain().preference_observation(
            item="ramen",
            merchant="Ramen House",
            context={"weekday": "friday", "daypart": "evening"},
        )
        self.assertEqual(
            observation,
            {
                "domain": "food",
                "item": "ramen",
                "signal": "selected",
                "provider": "doordash",
                "merchant": "Ramen House",
                "context": {"weekday": "friday", "daypart": "evening"},
            },
        )

    def test_untrusted_urls_and_oversized_fields_are_rejected(self):
        with self.assertRaisesRegex(DoorDashError, "item"):
            DoorDashDomain().prepare(item="")
        with self.assertRaisesRegex(DoorDashError, "item"):
            DoorDashDomain().prepare(item="x" * 300)
        with self.assertRaisesRegex(DoorDashError, "modifier"):
            DoorDashDomain().prepare(item="tacos", modifiers=["x" * 300])


if __name__ == "__main__":
    unittest.main()
