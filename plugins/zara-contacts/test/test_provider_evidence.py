import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_contacts.domain import ContactsDomain


CONTACT = {
    "contact_id": "contact-1",
    "display_name": "Ada Example",
    "aliases": [],
    "emails": ["ada@example.test"],
    "phones": [],
    "organizations": [],
    "handles": [],
    "sources": [
        {"provider": "test", "record_id": "record-1", "confidence": 1.0},
    ],
}


class MalformedAcceptanceBackend:
    def get_contact(self, contact_id):
        return dict(CONTACT) if contact_id == CONTACT["contact_id"] else None

    def create_contact(self, contact):
        return {"accepted": "false", "contact_id": CONTACT["contact_id"]}

    def update_contact(self, contact_id, patch):
        return {"accepted": "false", "contact_id": contact_id}


class ContactsProviderEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.contacts = ContactsDomain(MalformedAcceptanceBackend())

    def test_create_rejects_truthy_non_boolean_acceptance(self):
        candidate = dict(CONTACT)
        candidate.pop("contact_id")
        result = self.contacts.create(candidate)
        self.assertFalse(result["accepted"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["status"], "verification_failed")

    def test_update_rejects_truthy_non_boolean_acceptance(self):
        result = self.contacts.update(CONTACT["contact_id"], {"display_name": "Changed"})
        self.assertFalse(result["accepted"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["status"], "verification_failed")


if __name__ == "__main__":
    unittest.main()
