import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_calendar.domain import CalendarDomain


EVENT = {
    "event_id": "evt-1",
    "calendar_id": "work",
    "title": "Standup",
    "start": "2026-09-05T09:00:00-04:00",
    "end": "2026-09-05T09:30:00-04:00",
    "timezone": "America/New_York",
    "attendees": [],
    "recurrence": None,
    "reminders": [],
    "version": "v1",
}


class MalformedAcceptanceBackend:
    def __init__(self):
        self.event = dict(EVENT)

    def get_event(self, event_id):
        return dict(self.event) if event_id == self.event["event_id"] else None

    def create_event(self, event):
        return {"accepted": "false", "event_id": "evt-1", "version": "v1"}

    def update_event(self, event_id, expected_version, patch):
        return {"accepted": "false", "event_id": event_id, "version": expected_version}

    def delete_event(self, event_id, expected_version):
        return {"accepted": "false", "event_id": event_id, "version": expected_version}


class CalendarProviderEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.calendar = CalendarDomain(MalformedAcceptanceBackend())

    def test_create_rejects_truthy_non_boolean_acceptance(self):
        result = self.calendar.create(
            calendar_id="work",
            title="Planning",
            start="2026-09-05T13:00:00-04:00",
            end="2026-09-05T14:00:00-04:00",
            timezone_name="America/New_York",
            attendees=[],
            recurrence=None,
            reminders=[],
        )
        self.assertFalse(result["accepted"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["status"], "verification_failed")

    def test_update_rejects_truthy_non_boolean_acceptance(self):
        result = self.calendar.update("evt-1", "v1", {"title": "Changed"})
        self.assertFalse(result["accepted"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["status"], "verification_failed")

    def test_delete_rejects_truthy_non_boolean_acceptance(self):
        result = self.calendar.delete("evt-1", "v1")
        self.assertFalse(result["accepted"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["status"], "verification_failed")


if __name__ == "__main__":
    unittest.main()
