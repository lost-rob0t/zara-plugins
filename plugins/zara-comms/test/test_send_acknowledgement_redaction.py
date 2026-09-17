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
    def __init__(self, evidence, observed=None):
        self.evidence = evidence
        self.observed = observed
        self.get_calls = []

    def send(self, draft):
        return deepcopy(self.evidence)

    def get(self, message_id):
        self.get_calls.append(message_id)
        return deepcopy(self.observed)


def message():
    return {
        "provider": "gmail",
        "account_id": "acct-1",
        "conversation_id": "conv-1",
        "message_id": "msg-1",
        "sender": "me@example.test",
        "recipients": ["alice@example.test"],
        "timestamp": "2026-09-17T13:00:00+00:00",
        "body": "hello",
        "attachments": [],
        "read": True,
        "reply_to": "msg-0",
    }


def draft():
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


class SendAcknowledgementRedactionTest(unittest.TestCase):
    def test_send_returns_only_bounded_public_acknowledgement_evidence(self):
        secret = "provider-token-SENTINEL"
        provider = Provider(
            {
                "accepted": True,
                "message_id": "msg-1",
                "authorization": f"Bearer {secret}",
                "raw_provider_body": "x" * 100_000,
            },
            message(),
        )

        result = CommsDomain({"gmail": provider}, Resolver()).send(draft())

        self.assertTrue(result["verified"])
        self.assertEqual(result["evidence"], {"accepted": True, "message_id": "msg-1"})
        self.assertNotIn(secret, repr(result))
        self.assertNotIn("raw_provider_body", result["evidence"])

    def test_invalid_message_id_fails_closed_without_provider_readback(self):
        secret = "diagnostic-SENTINEL"
        provider = Provider(
            {
                "accepted": True,
                "message_id": "m" * 257,
                "diagnostic": secret,
            },
            message(),
        )

        result = CommsDomain({"gmail": provider}, Resolver()).send(draft())

        self.assertTrue(result["accepted"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["status"], "verification_failed")
        self.assertEqual(result["evidence"], {"accepted": True})
        self.assertEqual(provider.get_calls, [])
        self.assertNotIn(secret, repr(result))


if __name__ == "__main__":
    unittest.main()
