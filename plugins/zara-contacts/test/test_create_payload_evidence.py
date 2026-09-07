import sys
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_contacts.domain import ContactsDomain


CANDIDATE = {
    "display_name": "Alice Example",
    "aliases": ["Alice"],
    "emails": ["alice@example.test"],
    "phones": ["+15551234567"],
    "organizations": [{"name": "Example", "role": "Engineer"}],
    "handles": [{"provider": "matrix", "value": "@alice:example.test"}],
    "sources": [{"provider": "manual", "record_id": "seed-1", "confidence": 1.0}],
}


class Provider:
    def __init__(self, observed):
        self.observed = observed

    def create_contact(self, candidate):
        return {"accepted": True, "contact_id": "contact-1"}

    def get_contact(self, contact_id):
        return deepcopy(self.observed)


class CreatePayloadEvidenceTest(unittest.TestCase):
    def result(self, observed):
        return ContactsDomain(Provider(observed)).create(deepcopy(CANDIDATE))

    def observed(self):
        return {"contact_id": "contact-1", **deepcopy(CANDIDATE)}

    def test_create_rejects_observed_payload_mismatch(self):
        mutations = (
            ("display_name", "Mallory Example"),
            ("aliases", ["Mallory"]),
            ("emails", ["mallory@example.test"]),
            ("phones", ["+15557654321"]),
            ("organizations", [{"name": "Other", "role": "Engineer"}]),
            ("handles", [{"provider": "matrix", "value": "@mallory:example.test"}]),
            ("sources", [{"provider": "manual", "record_id": "other", "confidence": 1.0}]),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                observed = self.observed()
                observed[field] = value
                result = self.result(observed)
                self.assertTrue(result["accepted"])
                self.assertFalse(result["verified"])
                self.assertEqual(result["status"], "verification_failed")

    def test_create_accepts_exact_observed_payload_with_provider_id(self):
        result = self.result(self.observed())
        self.assertTrue(result["verified"])
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["contact"]["contact_id"], "contact-1")


if __name__ == "__main__":
    unittest.main()
