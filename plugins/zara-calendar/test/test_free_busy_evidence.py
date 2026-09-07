import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_calendar.domain import CalendarDomain, CalendarError


class FreeBusyBackend:
    def __init__(self, values):
        self.values = values

    def free_busy(self, start, end, calendar_ids):
        return self.values


class FreeBusyEvidenceTest(unittest.TestCase):
    def calendar(self, values):
        return CalendarDomain(FreeBusyBackend(values), max_results=8)

    def test_free_busy_rejects_malformed_provider_entries(self):
        malformed = (
            "busy",
            {},
            {"calendar_id": "work", "start": "2026-09-07T01:00:00", "end": "2026-09-07T02:00:00+00:00"},
            {"calendar_id": "work", "start": "2026-09-07T02:00:00+00:00", "end": "2026-09-07T01:00:00+00:00"},
            {"calendar_id": "other", "start": "2026-09-07T01:00:00+00:00", "end": "2026-09-07T02:00:00+00:00"},
            {"calendar_id": "work", "start": "2026-09-07T01:00:00+00:00", "end": "2026-09-07T02:00:00+00:00", "event_id": 7},
            {"calendar_id": "work", "start": "2026-09-07T01:00:00+00:00", "end": "2026-09-07T02:00:00+00:00", "provider_private": "opaque"},
        )
        for value in malformed:
            with self.subTest(value=value):
                calendar = self.calendar([value])
                with self.assertRaises(CalendarError):
                    calendar.free_busy(
                        "2026-09-07T00:00:00+00:00",
                        "2026-09-07T03:00:00+00:00",
                        ["work"],
                    )

    def test_free_busy_returns_validated_bounded_interval(self):
        interval = {
            "calendar_id": "work",
            "start": "2026-09-07T01:00:00+00:00",
            "end": "2026-09-07T02:00:00+00:00",
            "event_id": "evt-1",
        }
        result = self.calendar([interval] * 12).free_busy(
            "2026-09-07T00:00:00+00:00",
            "2026-09-07T03:00:00+00:00",
            ["work"],
        )
        self.assertEqual(result, [interval] * 8)


if __name__ == "__main__":
    unittest.main()
