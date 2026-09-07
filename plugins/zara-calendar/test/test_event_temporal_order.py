import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_calendar.domain import CalendarDomain, CalendarError


EVENT = {
    "event_id": "evt-1",
    "calendar_id": "work",
    "title": "Review",
    "start": "2026-09-07T10:00:00+00:00",
    "end": "2026-09-07T11:00:00+00:00",
    "timezone": "UTC",
    "attendees": [],
    "recurrence": None,
    "reminders": [],
    "version": "v1",
}


class EventTemporalOrderTest(unittest.TestCase):
    def test_provider_event_end_must_be_after_start(self):
        for end in (
            "2026-09-07T10:00:00+00:00",
            "2026-09-07T09:59:59+00:00",
        ):
            with self.subTest(end=end):
                with self.assertRaisesRegex(CalendarError, "end"):
                    CalendarDomain._event(dict(EVENT, end=end))

    def test_valid_provider_event_is_unchanged(self):
        self.assertEqual(CalendarDomain._event(dict(EVENT)), EVENT)


if __name__ == "__main__":
    unittest.main()
