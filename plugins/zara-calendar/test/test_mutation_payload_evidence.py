import sys
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_calendar.domain import CalendarDomain


EVENT = {
    "event_id": "evt-1",
    "calendar_id": "work",
    "title": "Review",
    "start": "2026-09-07T10:00:00+00:00",
    "end": "2026-09-07T11:00:00+00:00",
    "timezone": "UTC",
    "attendees": ["alice@example.test"],
    "recurrence": None,
    "reminders": [{"minutes_before": 10}],
    "version": "v1",
}


class Backend:
    def __init__(self, observed):
        self.observed = deepcopy(observed)

    def create_event(self, event):
        return {"accepted": True, "event_id": "evt-1", "version": "v2"}

    def get_event(self, event_id):
        return deepcopy(self.observed)

    def update_event(self, event_id, expected_version, patch):
        return {"accepted": True, "event_id": event_id, "version": "v2"}


class MutationPayloadEvidenceTest(unittest.TestCase):
    def create_result(self, observed):
        domain = CalendarDomain(Backend(observed))
        return domain.create(
            calendar_id="work",
            title="Review",
            start="2026-09-07T10:00:00+00:00",
            end="2026-09-07T11:00:00+00:00",
            timezone_name="UTC",
            attendees=["alice@example.test"],
            recurrence=None,
            reminders=[{"minutes_before": 10}],
        )

    def test_create_rejects_observed_payload_mismatch_even_with_matching_version(self):
        mismatches = (
            ("calendar_id", "other"),
            ("title", "Different"),
            ("end", "2026-09-07T11:30:00+00:00"),
            ("attendees", ["mallory@example.test"]),
        )
        for field, value in mismatches:
            with self.subTest(field=field):
                observed = dict(EVENT, version="v2")
                observed[field] = value
                result = self.create_result(observed)
                self.assertTrue(result["accepted"])
                self.assertFalse(result["verified"])

    def test_create_accepts_exact_payload_with_provider_identity_fields(self):
        result = self.create_result(dict(EVENT, version="v2"))
        self.assertTrue(result["verified"])

    def test_update_rejects_observed_payload_mismatch_even_with_matching_version(self):
        observed = dict(EVENT, title="Unrelated", version="v2")
        domain = CalendarDomain(Backend(observed))
        result = domain.update("evt-1", "v1", {"title": "Updated"})
        self.assertTrue(result["accepted"])
        self.assertFalse(result["verified"])


if __name__ == "__main__":
    unittest.main()
