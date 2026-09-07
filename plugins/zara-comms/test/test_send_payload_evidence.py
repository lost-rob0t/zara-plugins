import sys
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_comms.domain import CommsDomain


OBSERVED = {
    "provider": "gmail",
    "account_id": "acct-mail",
    "conversation_id": "thread-sent-1",
    "message_id": "sent-1",
    "sender": "me@example.test",
    "recipients": ["alice@example.test"],
    "timestamp": "2026-09-07T06:30:00+00:00",
    "body": "hello",
    "attachments": [],
    "read": True,
    "reply_to": None,
}

DRAFT = {
    "status": "draft",
    "provider": "gmail",
    "account_id": "acct-mail",
    "conversation_id": None,
    "recipients": ["alice@example.test"],
    "subject": "",
    "body": "hello",
    "reply_to": None,
}


class Resolver:
    def resolve(self, query, channel):
        raise AssertionError("resolver should not be used")


class EvidenceProvider:
    def __init__(self, observed):
        self.observed = observed

    def send(self, draft):
        return {"accepted": True, "message_id": "sent-1"}

    def get(self, message_id):
        return deepcopy(self.observed)


class SendPayloadEvidenceTest(unittest.TestCase):
    def result(self, observed):
        provider = EvidenceProvider(observed)
        comms = CommsDomain({"gmail": provider}, Resolver())
        return comms.send(dict(DRAFT))

    def test_send_rejects_observed_payload_mismatch(self):
        mismatches = (
            {"account_id": "other-account"},
            {"recipients": ["mallory@example.test"]},
            {"body": "different body"},
            {"reply_to": "m0"},
        )
        for patch in mismatches:
            with self.subTest(patch=patch):
                observed = dict(OBSERVED)
                observed.update(patch)
                result = self.result(observed)
                self.assertTrue(result["accepted"])
                self.assertFalse(result["verified"])
                self.assertEqual(result["status"], "verification_failed")

    def test_matching_observed_payload_verifies(self):
        self.assertTrue(self.result(dict(OBSERVED))["verified"])


if __name__ == "__main__":
    unittest.main()
