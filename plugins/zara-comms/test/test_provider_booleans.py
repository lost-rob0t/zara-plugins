import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_comms.domain import CommsDomain, CommsError


MESSAGE = {
    "provider": "gmail",
    "account_id": "acct-mail",
    "conversation_id": "thread-1",
    "message_id": "m1",
    "sender": "boss@example.test",
    "recipients": ["alice@example.test"],
    "timestamp": "2026-09-05T08:00:00+00:00",
    "body": "status",
    "attachments": [],
    "read": "false",
    "reply_to": None,
}


class MalformedProvider:
    def get(self, message_id):
        if message_id == "m1":
            return dict(MESSAGE)
        return None

    def send(self, draft):
        return {"accepted": "false", "message_id": "m1"}


class Resolver:
    def resolve(self, query, channel):
        return {"status": "resolved", "recipient": {"channel": channel, "value": "alice@example.test"}}


class CommsProviderBooleanTest(unittest.TestCase):
    def setUp(self):
        self.comms = CommsDomain({"gmail": MalformedProvider()}, Resolver())

    def test_message_read_requires_exact_boolean(self):
        with self.assertRaisesRegex(CommsError, "read"):
            self.comms.get("gmail", "m1")

    def test_send_rejects_truthy_non_boolean_acceptance(self):
        draft = {
            "status": "draft",
            "provider": "gmail",
            "account_id": "acct-mail",
            "conversation_id": None,
            "recipients": ["alice@example.test"],
            "subject": "",
            "body": "hello",
            "reply_to": None,
        }
        result = self.comms.send(draft)
        self.assertFalse(result["accepted"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["status"], "verification_failed")


if __name__ == "__main__":
    unittest.main()
