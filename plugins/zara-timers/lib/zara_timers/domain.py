from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


class TimerError(RuntimeError):
    pass


class SystemClock:
    @staticmethod
    def monotonic():
        import time
        return time.monotonic()

    @staticmethod
    def now():
        return datetime.now(timezone.utc)


class TimerDomain:
    def __init__(self, state_path, *, clock=None, missed_policy="fire_once"):
        if missed_policy not in {"fire_once", "skip"}:
            raise TimerError("missed_policy must be fire_once or skip")
        self.state_path = Path(state_path).expanduser()
        self.clock = clock or SystemClock()
        self.missed_policy = missed_policy
        self._events = []
        self._items = {}
        self._sequence = 0
        self._load()

    @staticmethod
    def _aware(value, name="time"):
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError) as error:
            raise TimerError(f"{name} is invalid") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise TimerError(f"{name} must include timezone information")
        return parsed

    @staticmethod
    def _name(value):
        if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > 512:
            raise TimerError("name is invalid")
        return value

    def _load(self):
        if not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if data.get("schema_version") != 1 or not isinstance(data.get("items"), list):
                raise ValueError("schema")
            self._sequence = int(data.get("sequence", 0))
            for raw in data["items"]:
                item = dict(raw)
                item_id = item["id"]
                if item["kind"] == "timer" and item["status"] == "running":
                    saved_at = self._aware(item["saved_at"], "saved_at")
                    elapsed = max(0.0, (self.clock.now() - saved_at).total_seconds())
                    item["remaining"] = max(0.0, float(item["remaining"]) - elapsed)
                self._items[item_id] = item
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            raise TimerError("timer state is invalid or unrecoverable") from error

    def _persist(self):
        now = self.clock.now().isoformat()
        values = []
        for item_id in sorted(self._items):
            item = dict(self._items[item_id])
            if item["kind"] == "timer" and item["status"] == "running":
                item["remaining"] = self._remaining(self._items[item_id])
                item["saved_at"] = now
                self._items[item_id]["remaining"] = item["remaining"]
                self._items[item_id]["started_mono"] = self.clock.monotonic()
                self._items[item_id]["saved_at"] = now
            item.pop("started_mono", None)
            values.append(item)
        payload = {"schema_version": 1, "sequence": self._sequence, "items": values}
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".zara-timers-", dir=self.state_path.parent, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.state_path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def _next_id(self, prefix):
        self._sequence += 1
        return f"{prefix}-{self._sequence:08d}"

    def _remaining(self, item):
        if item["status"] == "paused":
            return max(0.0, float(item["remaining"]))
        elapsed = max(0.0, self.clock.monotonic() - float(item["started_mono"]))
        return max(0.0, float(item["remaining"]) - elapsed)

    def _public(self, item):
        result = {key: value for key, value in item.items() if key not in {"remaining", "started_mono", "saved_at"}}
        if item["kind"] == "timer":
            result["remaining_seconds"] = int(round(self._remaining(item)))
        return result

    def create_timer(self, name, duration_seconds):
        duration = float(duration_seconds)
        if not 0 < duration <= 31_536_000:
            raise TimerError("duration_seconds is out of range")
        item = {
            "id": self._next_id("timer"), "kind": "timer", "name": self._name(name),
            "status": "running", "remaining": duration, "started_mono": self.clock.monotonic(),
            "saved_at": self.clock.now().isoformat(),
        }
        self._items[item["id"]] = item
        self._persist()
        return self._public(item)

    def create_alarm(self, name, due_at):
        due = self._aware(due_at, "due_at")
        item = {"id": self._next_id("alarm"), "kind": "alarm", "name": self._name(name), "status": "scheduled", "due_at": due.isoformat()}
        self._items[item["id"]] = item
        self._persist()
        return self._public(item)

    def create_reminder(self, name, due_at, *, cadence_seconds, timezone_name):
        due = self._aware(due_at, "due_at")
        cadence = int(cadence_seconds)
        if not 1 <= cadence <= 31_536_000:
            raise TimerError("cadence_seconds is out of range")
        if not isinstance(timezone_name, str) or not timezone_name.strip() or len(timezone_name) > 128:
            raise TimerError("timezone is invalid")
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(timezone_name)
        except Exception as error:
            raise TimerError("timezone is invalid") from error
        item = {
            "id": self._next_id("reminder"), "kind": "reminder", "name": self._name(name),
            "status": "scheduled", "due_at": due.isoformat(), "cadence_seconds": cadence, "timezone": timezone_name,
        }
        self._items[item["id"]] = item
        self._persist()
        return self._public(item)

    def get(self, item_id):
        item = self._items.get(item_id)
        if item is None:
            raise TimerError("timer does not exist")
        return self._public(item)

    def list(self):
        return [self._public(self._items[key]) for key in sorted(self._items)]

    def pause(self, item_id):
        item = self._items.get(item_id)
        if item is None or item["kind"] != "timer":
            raise TimerError("timer does not exist")
        if item["status"] == "cancelled":
            raise TimerError("timer is cancelled")
        if item["status"] == "running":
            item["remaining"] = self._remaining(item)
            item["status"] = "paused"
            item.pop("started_mono", None)
            self._persist()
        return self._public(item)

    def resume(self, item_id):
        item = self._items.get(item_id)
        if item is None or item["kind"] != "timer":
            raise TimerError("timer does not exist")
        if item["status"] == "cancelled":
            raise TimerError("timer is cancelled")
        if item["status"] == "paused":
            item["status"] = "running"
            item["started_mono"] = self.clock.monotonic()
            item["saved_at"] = self.clock.now().isoformat()
            self._persist()
        return self._public(item)

    def cancel(self, item_id):
        item = self._items.get(item_id)
        if item is None:
            raise TimerError("timer does not exist")
        if item["status"] != "cancelled":
            item["status"] = "cancelled"
            self._events.append({"type": "cancelled", "timer_id": item_id, "at": self.clock.now().isoformat()})
            self._persist()
        return self._public(item)

    def _fire(self, item):
        self._events.append({"type": "fired", "timer_id": item["id"], "kind": item["kind"], "at": self.clock.now().isoformat()})
        if item["kind"] == "reminder":
            due = self._aware(item["due_at"], "due_at")
            cadence = timedelta(seconds=item["cadence_seconds"])
            while due <= self.clock.now():
                due += cadence
            item["due_at"] = due.isoformat()
        else:
            item["status"] = "fired"

    def poll_due(self):
        before = len(self._events)
        now = self.clock.now()
        for item in self._items.values():
            if item["status"] in {"cancelled", "fired", "paused"}:
                continue
            if item["kind"] == "timer":
                if self._remaining(item) <= 0:
                    self._fire(item)
            else:
                due = self._aware(item["due_at"], "due_at")
                if due <= now:
                    if self.missed_policy == "fire_once":
                        self._fire(item)
                    elif item["kind"] == "reminder":
                        cadence = timedelta(seconds=item["cadence_seconds"])
                        while due <= now:
                            due += cadence
                        item["due_at"] = due.isoformat()
                    else:
                        item["status"] = "fired"
        if len(self._events) != before:
            self._persist()
        return list(self._events[before:])

    def drain_events(self):
        events = list(self._events)
        self._events.clear()
        return events
