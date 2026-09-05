import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_timers.domain import TimerDomain, TimerError


class FakeClock:
    def __init__(self):
        self.mono = 100.0
        self.wall = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)

    def monotonic(self):
        return self.mono

    def now(self):
        return self.wall

    def advance(self, seconds):
        from datetime import timedelta
        self.mono += seconds
        self.wall += timedelta(seconds=seconds)


class TimerDomainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.state = Path(self.tmp.name) / "timers.json"
        self.timers = TimerDomain(self.state, clock=self.clock, missed_policy="fire_once")

    def tearDown(self):
        self.tmp.cleanup()

    def test_countdown_uses_monotonic_time_and_stable_id(self):
        created = self.timers.create_timer("tea", 30)
        self.assertEqual(created["kind"], "timer")
        self.assertTrue(created["id"].startswith("timer-"))
        self.clock.advance(10)
        current = self.timers.get(created["id"])
        self.assertEqual(current["remaining_seconds"], 20)

    def test_pause_resume_preserves_remaining_countdown(self):
        created = self.timers.create_timer("focus", 60)
        self.clock.advance(15)
        paused = self.timers.pause(created["id"])
        self.assertEqual(paused["remaining_seconds"], 45)
        self.clock.advance(100)
        self.assertEqual(self.timers.get(created["id"])["remaining_seconds"], 45)
        self.timers.resume(created["id"])
        self.clock.advance(5)
        self.assertEqual(self.timers.get(created["id"])["remaining_seconds"], 40)

    def test_alarm_requires_timezone_aware_wall_clock(self):
        with self.assertRaisesRegex(TimerError, "timezone"):
            self.timers.create_alarm("bad", "2026-09-05T13:00:00")
        alarm = self.timers.create_alarm("meeting", "2026-09-05T13:00:00+00:00")
        self.assertEqual(alarm["kind"], "alarm")
        self.assertEqual(alarm["due_at"], "2026-09-05T13:00:00+00:00")

    def test_recurring_reminder_preserves_timezone_and_cadence(self):
        item = self.timers.create_reminder(
            "meds",
            "2026-09-05T12:05:00+00:00",
            cadence_seconds=3600,
            timezone_name="UTC",
        )
        self.assertEqual(item["kind"], "reminder")
        self.assertEqual(item["timezone"], "UTC")
        self.assertEqual(item["cadence_seconds"], 3600)
        self.clock.advance(300)
        events = self.timers.poll_due()
        self.assertEqual(events[0]["type"], "fired")
        self.assertEqual(events[0]["timer_id"], item["id"])
        self.assertEqual(self.timers.get(item["id"])["due_at"], "2026-09-05T13:05:00+00:00")

    def test_persistence_restart_recovers_countdown_without_store_mutation(self):
        item = self.timers.create_timer("persist", 90)
        raw = self.state.read_text()
        self.assertNotIn(str(self.clock.monotonic()), raw)
        self.clock.advance(30)
        restarted = TimerDomain(self.state, clock=self.clock, missed_policy="fire_once")
        self.assertEqual(restarted.get(item["id"])["remaining_seconds"], 60)

    def test_missed_fire_once_policy_emits_one_event_after_downtime(self):
        item = self.timers.create_alarm("wake", "2026-09-05T12:01:00+00:00")
        self.clock.advance(300)
        restarted = TimerDomain(self.state, clock=self.clock, missed_policy="fire_once")
        events = restarted.poll_due()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["timer_id"], item["id"])
        self.assertEqual(restarted.poll_due(), [])

    def test_cancel_emits_event_and_is_stable(self):
        item = self.timers.create_timer("cancel me", 10)
        result = self.timers.cancel(item["id"])
        self.assertEqual(result["status"], "cancelled")
        events = self.timers.drain_events()
        self.assertEqual(events[-1]["type"], "cancelled")
        with self.assertRaisesRegex(TimerError, "cancelled"):
            self.timers.resume(item["id"])

    def test_state_is_deterministic_json_and_corruption_fails_closed(self):
        self.timers.create_timer("a", 10)
        parsed = json.loads(self.state.read_text())
        self.assertEqual(parsed["schema_version"], 1)
        self.state.write_text("{broken")
        with self.assertRaisesRegex(TimerError, "state"):
            TimerDomain(self.state, clock=self.clock)


if __name__ == "__main__":
    unittest.main()
