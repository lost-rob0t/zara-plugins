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
    "title": "Planning",
    "start": "2026-09-07T13:00:00-04:00",
    "end": "2026-09-07T14:00:00-04:00",
    "timezone": "America/New_York",
    "attendees": [],
    "recurrence": None,
    "reminders": [],
    "version": "v2",
}


class Backend:
    def __init__(self, observed):
        self.observed = observed

    def create_event(self, event):
        return {"accepted": True, "event_id": "evt-1", "version": "v2"}

    def update_event(self, event_id, expected_version, patch):
        return {"accepted": True, "event_id": event_id, "version": "v2"}

    def get_event(self, event_id):
        return deepcopy(self.observed) if event_id == "evt-1" else None


class WritePayloadEvidenceTest(unittest.TestCase):
    def create(self, observed):
        return CalendarDomain(Backend(observed)).create(
            calendar_id="work",
            title="Planning",
            start="2026-09-07T13:00:00-04:00",
            end="2026-09-07T14:00:00-04:00",
            timezone_name="America/New_York",
            attendees=[],
            recurrence=None,
            reminders=[],
        )

    def test_create_rejects_observed_payload_mismatch(self):
        observed = dict(EVENT, title="Different")
        result = self.create(observed)
        self.assertTrue(result["accepted"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["status"], "verification_failed")

    def test_create_accepts_matching_observed_payload(self):
        self.assertTrue(self.create(dict(EVENT))["verified"])

    def test_update_rejects_observed_payload_mismatch(self):
        backend = Backend(dict(EVENT))
        calendar = CalendarDomain(backend)
        backend.observed = dict(EVENT, title="Wrong title", version="v2")
        result = calendar.update("evt-1", "v1", {"title": "Changed"})
        self.assertTrue(result["accepted"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["status"], "verification_failed")


if __name__ == "__main__":
    unittest.main()
