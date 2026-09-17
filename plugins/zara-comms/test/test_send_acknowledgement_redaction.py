import sys
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara.agent.tools.registry import ToolRegistry
from zara_comms.domain import CommsDomain, CommsError
from zara_comms.plugin import ZaraCommsPlugin


class Resolver:
    pass


class Provider:
    def __init__(self, evidence, observed=None):
        self.evidence = evidence
        self.observed = observed
        self.get_calls = []
        self.send_calls = []

    def send(self, draft):
        self.send_calls.append(deepcopy(draft))
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

    def test_control_character_message_id_fails_closed_without_provider_readback(self):
        provider = Provider(
            {"accepted": True, "message_id": "msg-1\nforged-log-line"},
            message(),
        )

        result = CommsDomain({"gmail": provider}, Resolver()).send(draft())

        self.assertTrue(result["accepted"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["evidence"], {"accepted": True})
        self.assertEqual(provider.get_calls, [])

    def test_send_rejects_untrusted_thread_identifiers_before_provider_io(self):
        invalid_values = (42, "x" * 257, "thread\nforged")
        for field in ("conversation_id", "reply_to"):
            for invalid in invalid_values:
                with self.subTest(field=field, invalid=invalid):
                    provider = Provider({"accepted": True, "message_id": "msg-1"}, message())
                    candidate = draft()
                    candidate[field] = invalid

                    with self.assertRaises(CommsError):
                        CommsDomain({"gmail": provider}, Resolver()).send(candidate)

                    self.assertEqual(provider.send_calls, [])
                    self.assertEqual(provider.get_calls, [])

    def test_send_allows_absent_optional_thread_identifiers(self):
        observed = message()
        observed["conversation_id"] = "provider-thread"
        observed["reply_to"] = None
        provider = Provider({"accepted": True, "message_id": "msg-1"}, observed)
        candidate = draft()
        candidate["conversation_id"] = None
        candidate["reply_to"] = None

        result = CommsDomain({"gmail": provider}, Resolver()).send(candidate)

        self.assertTrue(result["verified"])
        self.assertIsNone(provider.send_calls[0]["conversation_id"])
        self.assertIsNone(provider.send_calls[0]["reply_to"])

    def test_send_tool_registers_as_approval_required_by_default(self):
        provider = Provider({"accepted": False})
        plugin = ZaraCommsPlugin(providers={"gmail": provider}, resolver=Resolver())
        tools = list(plugin.tools())
        registry = ToolRegistry()
        registry.register_tools(tools)

        self.assertTrue(registry.requires_approval("comms.send"))
        for name in ("comms.status", "comms.search", "comms.get", "comms.draft", "comms.draft_reply"):
            self.assertFalse(registry.requires_approval(name), name)


if __name__ == "__main__":
    unittest.main()
