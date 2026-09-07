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
        self.wall = datetime(2026, 9, 7, 1, 0, tzinfo=timezone.utc)

    def monotonic(self):
        return self.mono

    def now(self):
        return self.wall


class PersistedNumericTypeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "timers.json"
        self.clock = FakeClock()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, *, sequence=1, items=None):
        self.state.write_text(json.dumps({
            "schema_version": 1,
            "sequence": sequence,
            "items": [] if items is None else items,
        }))

    def timer(self, *, remaining=30):
        return {
            "id": "timer-00000001",
            "kind": "timer",
            "name": "tea",
            "status": "running",
            "remaining": remaining,
            "saved_at": "2026-09-07T01:00:00+00:00",
        }

    def reminder(self, *, cadence_seconds=60):
        return {
            "id": "reminder-00000001",
            "kind": "reminder",
            "name": "check",
            "status": "scheduled",
            "due_at": "2026-09-07T01:05:00+00:00",
            "cadence_seconds": cadence_seconds,
            "timezone": "UTC",
        }

    def test_sequence_requires_exact_non_negative_integer(self):
        for malformed in (True, "1", 1.5, -1):
            with self.subTest(sequence=malformed):
                self.write(sequence=malformed)
                with self.assertRaisesRegex(TimerError, "state"):
                    TimerDomain(self.state, clock=self.clock)

    def test_timer_remaining_rejects_coercible_or_non_finite_values(self):
        for malformed in (True, "30", float("nan"), float("inf"), -1, 31_536_001):
            with self.subTest(remaining=malformed):
                self.write(items=[self.timer(remaining=malformed)])
                with self.assertRaisesRegex(TimerError, "state"):
                    TimerDomain(self.state, clock=self.clock)

    def test_reminder_cadence_reuses_creation_contract(self):
        for malformed in (True, "60", 1.5, 0, 31_536_001):
            with self.subTest(cadence_seconds=malformed):
                self.write(items=[self.reminder(cadence_seconds=malformed)])
                with self.assertRaisesRegex(TimerError, "state"):
                    TimerDomain(self.state, clock=self.clock)


if __name__ == "__main__":
    unittest.main()
