import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_comms.domain import CommsDomain, CommsError


class FakeProvider:
    def __init__(self, provider, messages):
        self.provider = provider
        self.messages = {item["message_id"]: dict(item) for item in messages}
        self.sent = []
        self.accept_send = True

    def search(self, query, limit):
        return [dict(item) for item in self.messages.values() if query.lower() in item["body"].lower()][:limit]

    def get(self, message_id):
        item = self.messages.get(message_id)
        return None if item is None else dict(item)

    def send(self, draft):
        if not self.accept_send:
            return {"accepted": False}
        message_id = f"sent-{len(self.sent) + 1}"
        conversation_id = draft["conversation_id"] or f"thread-{message_id}"
        sender = "me@example.test" if self.provider == "gmail" else "@me:example.test"
        stored = {
            "provider": self.provider,
            "account_id": draft["account_id"],
            "conversation_id": conversation_id,
            "message_id": message_id,
            "sender": sender,
            "recipients": list(draft["recipients"]),
            "timestamp": "2026-09-05T08:40:00+00:00",
            "body": draft["body"],
            "attachments": [],
            "read": True,
            "reply_to": draft["reply_to"],
        }
        self.messages[message_id] = stored
        self.sent.append(message_id)
        return {"accepted": True, "message_id": message_id, "provider": self.provider}


class Resolver:
    def resolve(self, query, channel):
        if query == "ambiguous":
            return {"status": "ambiguous", "candidates": [{"contact_id": "p1"}, {"contact_id": "p2"}]}
        if query == "missing":
            return {"status": "not_found", "candidates": []}
        return {"status": "resolved", "recipient": {"channel": channel, "value": "alice@example.test"}}


class CommsDomainTest(unittest.TestCase):
    def setUp(self):
        gmail = FakeProvider("gmail", [{
            "provider": "gmail",
            "account_id": "acct-mail",
            "conversation_id": "thread-1",
            "message_id": "m1",
            "sender": "boss@example.test",
            "recipients": ["alice@example.test"],
            "timestamp": "2026-09-05T08:00:00+00:00",
            "body": "project status",
            "attachments": [{"attachment_id": "a1", "name": "report.txt", "size": 50, "content_type": "text/plain"}],
            "read": False,
            "reply_to": None,
        }])
        matrix = FakeProvider("matrix", [{
            "provider": "matrix",
            "account_id": "acct-chat",
            "conversation_id": "room-1",
            "message_id": "mx1",
            "sender": "@bob:example.test",
            "recipients": ["@alice:example.test"],
            "timestamp": "2026-09-05T08:05:00+00:00",
            "body": "project update",
            "attachments": [],
            "read": True,
            "reply_to": None,
        }])
        self.gmail = gmail
        self.comms = CommsDomain({"gmail": gmail, "matrix": matrix}, Resolver(), max_results=20, max_body_bytes=4096)

    def test_same_public_schema_normalizes_multiple_providers(self):
        results = self.comms.search("project")
        self.assertEqual({item["provider"] for item in results}, {"gmail", "matrix"})
        self.assertTrue(all("conversation_id" in item and "message_id" in item for item in results))

    def test_attachments_are_metadata_only_and_bounded(self):
        message = self.comms.get("gmail", "m1")
        self.assertEqual(message["attachments"][0]["name"], "report.txt")
        self.assertNotIn("content", message["attachments"][0])
        with self.assertRaises(CommsError):
            self.comms.normalize_message({**message, "attachments": [{"attachment_id": "a", "name": "x", "size": 999999999, "content_type": "x"}] * 100})

    def test_draft_is_separate_from_send(self):
        draft = self.comms.draft(provider="gmail", account_id="acct-mail", recipient_query="alice", subject="Hi", body="hello")
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(self.gmail.sent, [])
        sent = self.comms.send(draft)
        self.assertTrue(sent["verified"])
        self.assertEqual(len(self.gmail.sent), 1)

    def test_ambiguous_recipient_fails_before_provider_send(self):
        with self.assertRaisesRegex(CommsError, "ambiguous"):
            self.comms.draft(provider="gmail", account_id="acct-mail", recipient_query="ambiguous", subject="Hi", body="hello")
        self.assertEqual(self.gmail.sent, [])

    def test_reply_preserves_provider_and_thread_identity(self):
        draft = self.comms.draft_reply("gmail", "m1", "reply body")
        self.assertEqual(draft["conversation_id"], "thread-1")
        self.assertEqual(draft["reply_to"], "m1")
        sent = self.comms.send(draft)
        self.assertTrue(sent["verified"])
        self.assertEqual(sent["message"]["conversation_id"], "thread-1")

    def test_provider_rejection_never_claims_send_success(self):
        draft = self.comms.draft(provider="gmail", account_id="acct-mail", recipient_query="alice", subject="Hi", body="hello")
        self.gmail.accept_send = False
        result = self.comms.send(draft)
        self.assertFalse(result["accepted"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["status"], "verification_failed")

    def test_unknown_provider_and_oversized_body_fail_closed(self):
        with self.assertRaisesRegex(CommsError, "provider"):
            self.comms.get("slack", "x")
        with self.assertRaisesRegex(CommsError, "body"):
            self.comms.draft(provider="gmail", account_id="acct-mail", recipient_query="alice", subject="x", body="z" * 5000)


if __name__ == "__main__":
    unittest.main()
