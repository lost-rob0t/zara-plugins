import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_calendar.domain import CalendarDomain, CalendarError


class FakeCalendarBackend:
    def __init__(self):
        self.events = {
            "evt-1": {
                "event_id": "evt-1",
                "calendar_id": "work",
                "title": "Standup",
                "start": "2026-09-05T09:00:00-04:00",
                "end": "2026-09-05T09:30:00-04:00",
                "timezone": "America/New_York",
                "attendees": ["a@example.test"],
                "recurrence": {"rrule": "FREQ=DAILY;COUNT=5"},
                "reminders": [{"minutes_before": 10}],
                "version": "v1",
            },
            "evt-2": {
                "event_id": "evt-2",
                "calendar_id": "work",
                "title": "Review",
                "start": "2026-09-05T11:00:00-04:00",
                "end": "2026-09-05T12:00:00-04:00",
                "timezone": "America/New_York",
                "attendees": [],
                "recurrence": None,
                "reminders": [],
                "version": "v3",
            },
        }
        self.next_id = 3
        self.accept_mutations = True

    def search_events(self, start, end, text, calendar_id, limit):
        values = []
        for event in self.events.values():
            if calendar_id and event["calendar_id"] != calendar_id:
                continue
            if text and text.lower() not in event["title"].lower():
                continue
            if event["end"] <= start or event["start"] >= end:
                continue
            values.append(dict(event))
        return values[:limit]

    def get_event(self, event_id):
        value = self.events.get(event_id)
        return None if value is None else dict(value)

    def free_busy(self, start, end, calendar_ids):
        return [
            {"calendar_id": event["calendar_id"], "start": event["start"], "end": event["end"], "event_id": event["event_id"]}
            for event in self.events.values()
            if event["calendar_id"] in calendar_ids and event["end"] > start and event["start"] < end
        ]

    def create_event(self, event):
        if not self.accept_mutations:
            return {"accepted": False}
        event_id = f"evt-{self.next_id}"
        self.next_id += 1
        stored = dict(event)
        stored["event_id"] = event_id
        stored["version"] = "v1"
        self.events[event_id] = stored
        return {"accepted": True, "event_id": event_id, "version": "v1"}

    def update_event(self, event_id, expected_version, patch):
        if not self.accept_mutations:
            return {"accepted": False}
        current = self.events[event_id]
        if current["version"] != expected_version:
            return {"accepted": False, "reason": "version-conflict"}
        current.update(patch)
        current["version"] = "v-next"
        return {"accepted": True, "event_id": event_id, "version": "v-next"}

    def delete_event(self, event_id, expected_version):
        if not self.accept_mutations:
            return {"accepted": False}
        current = self.events.get(event_id)
        if current is None or current["version"] != expected_version:
            return {"accepted": False, "reason": "version-conflict"}
        del self.events[event_id]
        return {"accepted": True, "event_id": event_id, "version": expected_version}


class CalendarDomainTest(unittest.TestCase):
    def setUp(self):
        self.backend = FakeCalendarBackend()
        self.calendar = CalendarDomain(self.backend, max_results=8, max_window_days=31)

    def test_search_preserves_timezone_recurrence_attendees_and_reminders(self):
        results = self.calendar.search(
            "2026-09-05T08:00:00-04:00",
            "2026-09-05T13:00:00-04:00",
            text="stand",
            calendar_id="work",
        )
        self.assertEqual(len(results), 1)
        event = results[0]
        self.assertEqual(event["timezone"], "America/New_York")
        self.assertEqual(event["recurrence"]["rrule"], "FREQ=DAILY;COUNT=5")
        self.assertEqual(event["attendees"], ["a@example.test"])
        self.assertEqual(event["reminders"], [{"minutes_before": 10}])

    def test_search_requires_aware_times_and_bounded_window(self):
        with self.assertRaisesRegex(CalendarError, "timezone"):
            self.calendar.search("2026-09-05T08:00:00", "2026-09-05T09:00:00")
        with self.assertRaisesRegex(CalendarError, "window"):
            self.calendar.search("2026-09-01T00:00:00+00:00", "2026-11-01T00:00:00+00:00")

    def test_free_busy_and_conflict_explain_why_candidate_fails(self):
        busy = self.calendar.free_busy(
            "2026-09-05T08:30:00-04:00",
            "2026-09-05T10:00:00-04:00",
            ["work"],
        )
        self.assertEqual(busy[0]["event_id"], "evt-1")
        conflict = self.calendar.explain_conflicts(
            "2026-09-05T09:15:00-04:00",
            "2026-09-05T09:45:00-04:00",
            ["work"],
        )
        self.assertFalse(conflict["available"])
        self.assertEqual(conflict["conflicts"][0]["event_id"], "evt-1")
        self.assertIn("overlaps", conflict["explanation"])

    def test_suggestions_are_read_only_and_marked_as_suggestions(self):
        suggestions = self.calendar.suggest_times(
            "2026-09-05T08:00:00-04:00",
            "2026-09-05T14:00:00-04:00",
            duration_minutes=30,
            calendar_ids=["work"],
            step_minutes=30,
        )
        self.assertGreater(len(suggestions), 0)
        self.assertTrue(all(item["status"] == "suggestion" for item in suggestions))
        self.assertNotIn("event_id", suggestions[0])

    def test_create_returns_provider_identity_and_observed_event(self):
        result = self.calendar.create(
            calendar_id="work",
            title="Planning",
            start="2026-09-05T13:00:00-04:00",
            end="2026-09-05T14:00:00-04:00",
            timezone_name="America/New_York",
            attendees=["b@example.test"],
            recurrence=None,
            reminders=[{"minutes_before": 15}],
        )
        self.assertTrue(result["accepted"])
        self.assertTrue(result["verified"])
        self.assertTrue(result["event"]["event_id"].startswith("evt-"))
        self.assertEqual(result["event"]["version"], "v1")

    def test_update_requires_expected_version_and_explicit_attendee_patch(self):
        with self.assertRaisesRegex(CalendarError, "expected_version"):
            self.calendar.update("evt-2", "", {"title": "Changed"})
        updated = self.calendar.update("evt-2", "v3", {"title": "Changed"})
        self.assertTrue(updated["verified"])
        self.assertEqual(updated["event"]["attendees"], [])
        self.assertEqual(updated["event"]["title"], "Changed")
        attendee_update = self.calendar.update("evt-2", "v-next", {"attendees": ["x@example.test"]})
        self.assertEqual(attendee_update["event"]["attendees"], ["x@example.test"])

    def test_delete_requires_version_and_verifies_absence(self):
        result = self.calendar.delete("evt-2", "v3")
        self.assertTrue(result["accepted"])
        self.assertTrue(result["verified"])
        self.assertIsNone(self.backend.get_event("evt-2"))

    def test_rejected_mutation_never_claims_success(self):
        self.backend.accept_mutations = False
        result = self.calendar.delete("evt-2", "v3")
        self.assertFalse(result["accepted"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["status"], "verification_failed")

    def test_event_shape_rejects_invalid_recurrence_reminders_and_long_attendees(self):
        with self.assertRaises(CalendarError):
            self.calendar.create(
                calendar_id="work",
                title="Bad",
                start="2026-09-05T13:00:00-04:00",
                end="2026-09-05T14:00:00-04:00",
                timezone_name="America/New_York",
                attendees=["x@example.test"] * 300,
                recurrence={"rrule": "FREQ=SECONDLY" + "X" * 5000},
                reminders=[],
            )


if __name__ == "__main__":
    unittest.main()
