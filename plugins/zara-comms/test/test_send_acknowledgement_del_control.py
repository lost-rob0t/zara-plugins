import sys
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_comms.domain import CommsDomain


class Resolver:
    pass


class Provider:
    def __init__(self):
        self.get_calls = []

    def send(self, _draft):
        return {"accepted": True, "message_id": "msg-1\x7fforged"}

    def get(self, message_id):
        self.get_calls.append(message_id)
        return deepcopy(
            {
                "provider": "gmail",
                "account_id": "acct-1",
                "conversation_id": "conv-1",
                "message_id": message_id,
                "sender": "me@example.test",
                "recipients": ["alice@example.test"],
                "timestamp": "2026-09-17T13:00:00+00:00",
                "body": "hello",
                "attachments": [],
                "read": True,
                "reply_to": "msg-0",
            }
        )


class SendAcknowledgementDelControlTest(unittest.TestCase):
    def test_del_control_message_id_fails_closed_without_provider_readback(self):
        provider = Provider()
        candidate = {
            "status": "draft",
            "provider": "gmail",
            "account_id": "acct-1",
            "conversation_id": "conv-1",
            "recipients": ["alice@example.test"],
            "subject": "",
            "body": "hello",
            "reply_to": "msg-0",
        }

        result = CommsDomain({"gmail": provider}, Resolver()).send(candidate)

        self.assertTrue(result["accepted"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["status"], "verification_failed")
        self.assertEqual(result["evidence"], {"accepted": True})
        self.assertEqual(provider.get_calls, [])


if __name__ == "__main__":
    unittest.main()
