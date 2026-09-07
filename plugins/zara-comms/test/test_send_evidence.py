import sys
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_comms.domain import CommsDomain


class Provider:
    def __init__(self, observed):
        self.observed = observed

    def send(self, draft):
        return {"accepted": True, "message_id": "msg-1"}

    def get(self, message_id):
        return deepcopy(self.observed)


class SendEvidenceTest(unittest.TestCase):
    def base_message(self):
        return {
            "provider": "gmail",
            "account_id": "acct-1",
            "conversation_id": "conv-1",
            "message_id": "msg-1",
            "sender": "me@example.test",
            "recipients": ["alice@example.test"],
            "timestamp": "2026-09-07T02:00:00+00:00",
            "body": "hello",
            "attachments": [],
            "read": True,
            "reply_to": "msg-0",
        }

    def draft(self):
        return {
            "status": "draft",
            "provider": "gmail",
            "account_id": "acct-1",
            "conversation_id": "conv-1",
            "recipients": ["alice@example.test"],
            "subject": "",
            "body": "hello",
            "reply_to": "msg-0",
        }

    def test_send_requires_observed_payload_to_match_intent(self):
        mutations = (
            ("account_id", "acct-2"),
            ("recipients", ["mallory@example.test"]),
            ("body", "different"),
            ("reply_to", "msg-other"),
            ("conversation_id", "conv-other"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                observed = self.base_message()
                observed[field] = value
                result = CommsDomain({"gmail": Provider(observed)}, object()).send(self.draft())
                self.assertFalse(result["verified"])
                self.assertEqual(result["status"], "verification_failed")

    def test_send_accepts_exact_observed_payload(self):
        result = CommsDomain({"gmail": Provider(self.base_message())}, object()).send(self.draft())
        self.assertTrue(result["verified"])
        self.assertEqual(result["status"], "verified")


if __name__ == "__main__":
    unittest.main()
