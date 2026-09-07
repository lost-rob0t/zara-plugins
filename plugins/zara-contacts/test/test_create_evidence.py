import sys
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_contacts.domain import ContactsDomain


CONTACT = {
    "display_name": "Ada Example",
    "aliases": ["Ada"],
    "emails": ["ada@example.test"],
    "phones": ["+12025550123"],
    "organizations": [{"name": "Example Org", "role": "Engineer"}],
    "handles": [{"provider": "matrix", "value": "@ada:example.test"}],
    "sources": [{"provider": "test", "record_id": "record-1", "confidence": 1.0}],
}


class Backend:
    def __init__(self, observed):
        self.observed = observed

    def create_contact(self, contact):
        return {"accepted": True, "contact_id": "contact-1"}

    def get_contact(self, contact_id):
        return deepcopy(self.observed) if contact_id == "contact-1" else None


class CreateEvidenceTest(unittest.TestCase):
    def result(self, observed):
        return ContactsDomain(Backend(observed)).create(dict(CONTACT))

    def observed(self, **patch):
        value = {"contact_id": "contact-1", **deepcopy(CONTACT)}
        value.update(patch)
        return value

    def test_create_rejects_observed_payload_mismatch(self):
        mismatches = (
            {"display_name": "Mallory Example"},
            {"emails": ["mallory@example.test"]},
            {"phones": ["+12025550124"]},
        )
        for patch in mismatches:
            with self.subTest(patch=patch):
                result = self.result(self.observed(**patch))
                self.assertTrue(result["accepted"])
                self.assertFalse(result["verified"])
                self.assertEqual(result["status"], "verification_failed")

    def test_create_accepts_exact_observed_payload_with_provider_id(self):
        result = self.result(self.observed())
        self.assertTrue(result["verified"])
        self.assertEqual(result["status"], "verified")


if __name__ == "__main__":
    unittest.main()
