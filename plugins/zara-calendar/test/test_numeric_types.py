from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_calendar.domain import CalendarDomain, CalendarError


START = "2026-09-07T09:00:00+00:00"
END = "2026-09-07T11:00:00+00:00"


class Backend:
    def __init__(self) -> None:
        self.search_calls = 0
        self.free_busy_calls = 0

    def search_events(self, start, end, text, calendar_id, limit):
        self.search_calls += 1
        return []

    def free_busy(self, start, end, calendar_ids):
        self.free_busy_calls += 1
        return []


class CalendarNumericTypeTests(unittest.TestCase):
    def test_rejects_coercive_constructor_limits(self) -> None:
        for field in ("max_results", "max_window_days"):
            for value in (True, False, 1.5, "50", None):
                options = {"max_results": 50, "max_window_days": 90, field: value}
                with self.subTest(field=field, value=value):
                    with self.assertRaises(CalendarError):
                        CalendarDomain(Backend(), **options)

    def test_rejects_coercive_search_limit_before_backend_dispatch(self) -> None:
        backend = Backend()
        calendar = CalendarDomain(backend)
        for value in (True, False, 1.5, "1"):
            with self.subTest(value=value):
                with self.assertRaises(CalendarError):
                    calendar.search(START, END, limit=value)
                self.assertEqual(0, backend.search_calls)

    def test_rejects_coercive_suggestion_numbers_before_backend_dispatch(self) -> None:
        for field in ("duration_minutes", "step_minutes"):
            for value in (True, False, 1.5, "30", None):
                backend = Backend()
                calendar = CalendarDomain(backend)
                options = {
                    "duration_minutes": 30,
                    "step_minutes": 30,
                    "calendar_ids": ["primary"],
                    field: value,
                }
                with self.subTest(field=field, value=value):
                    with self.assertRaises(CalendarError):
                        calendar.suggest_times(START, END, **options)
                    self.assertEqual(0, backend.free_busy_calls)

    def test_rejects_coercive_reminder_offsets(self) -> None:
        base = {
            "event_id": "event-1",
            "calendar_id": "primary",
            "title": "Meeting",
            "start": START,
            "end": END,
            "timezone": "UTC",
            "attendees": [],
            "recurrence": None,
            "reminders": [],
            "version": "v1",
        }
        for value in (True, False, 1.5, "5", None):
            event = dict(base)
            event["reminders"] = [{"minutes_before": value}]
            with self.subTest(value=value):
                with self.assertRaises(CalendarError):
                    CalendarDomain._event(event)

    def test_accepts_integer_descriptors_inside_existing_bounds(self) -> None:
        calendar = CalendarDomain(Backend(), max_results=12, max_window_days=30)
        self.assertEqual(12, calendar.max_results)
        self.assertEqual(30, calendar.max_window_days)


if __name__ == "__main__":
    unittest.main()
