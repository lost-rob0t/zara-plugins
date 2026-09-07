import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_comms.domain import CommsDomain, CommsError


BASE = {
    "provider": "gmail",
    "account_id": "acct-mail",
    "conversation_id": "thread-1",
    "message_id": "m1",
    "sender": "boss@example.test",
    "recipients": ["alice@example.test"],
    "timestamp": "2026-09-05T08:00:00+00:00",
    "body": "status",
    "attachments": [],
    "read": False,
    "reply_to": None,
}


class CommsAttachmentSizeTypeTest(unittest.TestCase):
    def setUp(self):
        self.comms = CommsDomain({"gmail": object()}, object())

    def test_attachment_size_rejects_coercible_non_integers(self):
        for malformed in (True, "50", 1.5):
            with self.subTest(size=malformed):
                message = dict(BASE)
                message["attachments"] = [{
                    "attachment_id": "a1",
                    "name": "report.txt",
                    "size": malformed,
                    "content_type": "text/plain",
                }]
                with self.assertRaisesRegex(CommsError, "size"):
                    self.comms.normalize_message(message)


if __name__ == "__main__":
    unittest.main()
