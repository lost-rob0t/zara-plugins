import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_contacts.domain import ContactsDomain, ContactsError


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def search_contacts(self, query, limit):
        self.calls.append((query, limit))
        return []


def contact_with_confidence(confidence):
    return {
        "contact_id": "p1",
        "display_name": "Alice Example",
        "aliases": [],
        "emails": [],
        "phones": [],
        "organizations": [],
        "handles": [],
        "sources": [{"provider": "fixture", "record_id": "1", "confidence": confidence}],
    }


class ContactsNumericTypeTests(unittest.TestCase):
    def test_max_results_rejects_coercive_descriptors(self):
        for value in (True, False, "10", 10.5):
            with self.subTest(value=value):
                with self.assertRaises(ContactsError):
                    ContactsDomain(RecordingBackend(), max_results=value)

    def test_search_limit_rejects_coercive_descriptors_before_backend_dispatch(self):
        backend = RecordingBackend()
        domain = ContactsDomain(backend, max_results=20)
        for value in (True, False, "2", 2.5):
            with self.subTest(value=value):
                backend.calls.clear()
                with self.assertRaises(ContactsError):
                    domain.search("alice", limit=value)
                self.assertEqual([], backend.calls)

    def test_source_confidence_rejects_noncanonical_or_nonfinite_values(self):
        for value in (True, False, "0.5", math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaises(ContactsError):
                    ContactsDomain.normalize_contact(contact_with_confidence(value))

    def test_canonical_numeric_values_still_work(self):
        backend = RecordingBackend()
        domain = ContactsDomain(backend, max_results=20)
        self.assertEqual([], domain.search("alice", limit=2))
        self.assertEqual(("alice", 2), backend.calls[-1])
        normalized = domain.normalize_contact(contact_with_confidence(0.5))
        self.assertEqual(0.5, normalized["sources"][0]["confidence"])


if __name__ == "__main__":
    unittest.main()
