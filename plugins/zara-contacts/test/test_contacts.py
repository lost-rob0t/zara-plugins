import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_contacts.domain import ContactsDomain, ContactsError


class FakeContactsBackend:
    def __init__(self):
        self.contacts = {
            "p1": {
                "contact_id": "p1",
                "display_name": "Alice Example",
                "aliases": ["alice", "aexample"],
                "emails": ["alice@example.test"],
                "phones": ["+15550000001"],
                "organizations": [{"name": "Example Org", "role": "Engineer"}],
                "handles": [{"provider": "matrix", "value": "@alice:example.test"}],
                "sources": [{"provider": "local", "record_id": "1", "confidence": 1.0}],
            },
            "p2": {
                "contact_id": "p2",
                "display_name": "Alice Else",
                "aliases": ["alice"],
                "emails": ["else@example.test"],
                "phones": [],
                "organizations": [],
                "handles": [],
                "sources": [{"provider": "fixture", "record_id": "2", "confidence": 0.8}],
            },
        }
        self.accept_writes = True

    def search_contacts(self, query, limit):
        q = query.lower()
        values = []
        for contact in self.contacts.values():
            haystack = [contact["display_name"], *contact["aliases"], *contact["emails"]]
            if any(q in value.lower() for value in haystack):
                values.append(dict(contact))
        return values[:limit]

    def get_contact(self, contact_id):
        value = self.contacts.get(contact_id)
        return None if value is None else dict(value)

    def create_contact(self, contact):
        if not self.accept_writes:
            return {"accepted": False}
        contact_id = "p-new"
        stored = dict(contact)
        stored["contact_id"] = contact_id
        self.contacts[contact_id] = stored
        return {"accepted": True, "contact_id": contact_id}

    def update_contact(self, contact_id, patch):
        if not self.accept_writes:
            return {"accepted": False}
        self.contacts[contact_id].update(patch)
        return {"accepted": True, "contact_id": contact_id}


class ContactsDomainTest(unittest.TestCase):
    def setUp(self):
        self.backend = FakeContactsBackend()
        self.contacts = ContactsDomain(self.backend, max_results=20)

    def test_search_preserves_aliases_addresses_handles_and_provenance(self):
        result = self.contacts.search("Example")
        self.assertEqual(len(result), 1)
        contact = result[0]
        self.assertEqual(contact["contact_id"], "p1")
        self.assertEqual(contact["emails"], ["alice@example.test"])
        self.assertEqual(contact["phones"], ["+15550000001"])
        self.assertEqual(contact["handles"][0]["provider"], "matrix")
        self.assertEqual(contact["sources"][0]["provider"], "local")

    def test_ambiguous_resolution_returns_candidates_instead_of_guessing(self):
        result = self.contacts.resolve("alice", channel="email")
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual({item["contact_id"] for item in result["candidates"]}, {"p1", "p2"})
        self.assertNotIn("recipient", result)

    def test_channel_resolution_requires_address_for_requested_channel(self):
        result = self.contacts.resolve("Alice Example", channel="matrix")
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["recipient"]["value"], "@alice:example.test")
        missing = self.contacts.resolve("Alice Else", channel="phone")
        self.assertEqual(missing["status"], "unavailable")

    def test_invalid_addresses_and_duplicate_fields_fail_closed(self):
        with self.assertRaises(ContactsError):
            self.contacts.normalize_contact({
                "contact_id": "bad",
                "display_name": "Bad",
                "aliases": [],
                "emails": ["not-an-email"],
                "phones": [],
                "organizations": [],
                "handles": [],
                "sources": [],
            })
        with self.assertRaises(ContactsError):
            self.contacts.normalize_contact({
                "contact_id": "dup",
                "display_name": "Dup",
                "aliases": [],
                "emails": ["a@example.test", "a@example.test"],
                "phones": [],
                "organizations": [],
                "handles": [],
                "sources": [],
            })

    def test_create_and_update_require_backend_ack_and_observed_state(self):
        created = self.contacts.create({
            "display_name": "Bob Example",
            "aliases": ["bob"],
            "emails": ["bob@example.test"],
            "phones": [],
            "organizations": [],
            "handles": [],
            "sources": [{"provider": "local", "record_id": "new", "confidence": 1.0}],
        })
        self.assertTrue(created["verified"])
        updated = self.contacts.update("p-new", {"aliases": ["bob", "bobby"]})
        self.assertTrue(updated["verified"])
        self.assertEqual(updated["contact"]["aliases"], ["bob", "bobby"])

    def test_rejected_write_never_claims_success(self):
        self.backend.accept_writes = False
        result = self.contacts.update("p1", {"display_name": "Changed"})
        self.assertFalse(result["accepted"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["status"], "verification_failed")

    def test_confidence_and_sizes_are_bounded(self):
        with self.assertRaises(ContactsError):
            self.contacts.normalize_contact({
                "contact_id": "p3",
                "display_name": "Too Many",
                "aliases": [str(index) for index in range(300)],
                "emails": [],
                "phones": [],
                "organizations": [],
                "handles": [],
                "sources": [{"provider": "x", "record_id": "3", "confidence": 2.0}],
            })


if __name__ == "__main__":
    unittest.main()
