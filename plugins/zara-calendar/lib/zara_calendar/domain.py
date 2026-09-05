from __future__ import annotations

from datetime import datetime, timedelta


class CalendarError(RuntimeError):
    pass


class CalendarDomain:
    def __init__(self, backend, *, max_results: int = 50, max_window_days: int = 90) -> None:
        if not 1 <= int(max_results) <= 200:
            raise CalendarError("max_results is out of range")
        if not 1 <= int(max_window_days) <= 366:
            raise CalendarError("max_window_days is out of range")
        self.backend = backend
        self.max_results = int(max_results)
        self.max_window_days = int(max_window_days)

    @staticmethod
    def _text(value, name, limit=1024):
        if not isinstance(value, str) or not value.strip():
            raise CalendarError(f"{name} must be a non-empty string")
        if len(value.encode("utf-8")) > limit or any(ord(ch) < 0x20 for ch in value):
            raise CalendarError(f"{name} is invalid")
        return value

    @staticmethod
    def _time(value, name):
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError) as error:
            raise CalendarError(f"{name} is invalid") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise CalendarError(f"{name} must include timezone information")
        return parsed

    def _window(self, start, end):
        start_dt = self._time(start, "start")
        end_dt = self._time(end, "end")
        if end_dt <= start_dt:
            raise CalendarError("end must be after start")
        if end_dt - start_dt > timedelta(days=self.max_window_days):
            raise CalendarError("calendar window exceeds configured limit")
        return start_dt, end_dt

    @classmethod
    def _event(cls, event):
        if not isinstance(event, dict):
            raise CalendarError("calendar backend returned invalid event")
        required = {"event_id", "calendar_id", "title", "start", "end", "timezone", "attendees", "recurrence", "reminders", "version"}
        if not required.issubset(event):
            raise CalendarError("calendar event is missing required fields")
        cls._time(event["start"], "event start")
        cls._time(event["end"], "event end")
        attendees = event["attendees"]
        reminders = event["reminders"]
        recurrence = event["recurrence"]
        if not isinstance(attendees, list) or len(attendees) > 128:
            raise CalendarError("attendees are invalid")
        normalized_attendees = [cls._text(value, "attendee", 320) for value in attendees]
        if recurrence is not None:
            if not isinstance(recurrence, dict) or set(recurrence) - {"rrule"}:
                raise CalendarError("recurrence is invalid")
            cls._text(recurrence.get("rrule"), "recurrence rule", 2048)
        if not isinstance(reminders, list) or len(reminders) > 32:
            raise CalendarError("reminders are invalid")
        normalized_reminders = []
        for reminder in reminders:
            if not isinstance(reminder, dict) or set(reminder) != {"minutes_before"}:
                raise CalendarError("reminder is invalid")
            minutes = int(reminder["minutes_before"])
            if not 0 <= minutes <= 10080:
                raise CalendarError("reminder is out of range")
            normalized_reminders.append({"minutes_before": minutes})
        return {
            "event_id": cls._text(event["event_id"], "event id", 256),
            "calendar_id": cls._text(event["calendar_id"], "calendar id", 256),
            "title": cls._text(event["title"], "title"),
            "start": event["start"],
            "end": event["end"],
            "timezone": cls._text(event["timezone"], "timezone", 128),
            "attendees": normalized_attendees,
            "recurrence": recurrence,
            "reminders": normalized_reminders,
            "version": cls._text(event["version"], "version", 256),
        }

    def search(self, start, end, *, text=None, calendar_id=None, limit=None):
        self._window(start, end)
        if text is not None:
            text = self._text(text, "search text")
        if calendar_id is not None:
            calendar_id = self._text(calendar_id, "calendar id", 256)
        bounded = min(self.max_results, self.max_results if limit is None else int(limit))
        if bounded < 1:
            raise CalendarError("result limit is invalid")
        values = self.backend.search_events(start, end, text, calendar_id, bounded)
        if not isinstance(values, list):
            raise CalendarError("calendar backend returned invalid search results")
        return [self._event(value) for value in values[:bounded]]

    def get(self, event_id):
        event_id = self._text(event_id, "event id", 256)
        event = self.backend.get_event(event_id)
        return None if event is None else self._event(event)

    def free_busy(self, start, end, calendar_ids):
        self._window(start, end)
        if not isinstance(calendar_ids, list) or not 1 <= len(calendar_ids) <= 64:
            raise CalendarError("calendar_ids are invalid")
        ids = [self._text(value, "calendar id", 256) for value in calendar_ids]
        values = self.backend.free_busy(start, end, ids)
        if not isinstance(values, list):
            raise CalendarError("calendar backend returned invalid free/busy data")
        return values[: self.max_results]

    def explain_conflicts(self, start, end, calendar_ids):
        conflicts = self.free_busy(start, end, calendar_ids)
        return {
            "available": not conflicts,
            "conflicts": conflicts,
            "explanation": "available" if not conflicts else f"candidate overlaps {len(conflicts)} busy interval(s)",
        }

    def suggest_times(self, start, end, *, duration_minutes, calendar_ids, step_minutes=30):
        start_dt, end_dt = self._window(start, end)
        duration = int(duration_minutes)
        step = int(step_minutes)
        if not 1 <= duration <= 1440 or not 1 <= step <= 1440:
            raise CalendarError("duration or step is out of range")
        suggestions = []
        cursor = start_dt
        while cursor + timedelta(minutes=duration) <= end_dt and len(suggestions) < self.max_results:
            candidate_end = cursor + timedelta(minutes=duration)
            if not self.free_busy(cursor.isoformat(), candidate_end.isoformat(), calendar_ids):
                suggestions.append({"status": "suggestion", "start": cursor.isoformat(), "end": candidate_end.isoformat()})
            cursor += timedelta(minutes=step)
        return suggestions

    def _new_event(self, *, calendar_id, title, start, end, timezone_name, attendees, recurrence, reminders):
        self._window(start, end)
        candidate = {
            "event_id": "pending",
            "calendar_id": self._text(calendar_id, "calendar id", 256),
            "title": self._text(title, "title"),
            "start": start,
            "end": end,
            "timezone": self._text(timezone_name, "timezone", 128),
            "attendees": attendees,
            "recurrence": recurrence,
            "reminders": reminders,
            "version": "pending",
        }
        normalized = self._event(candidate)
        normalized.pop("event_id")
        normalized.pop("version")
        return normalized

    def create(self, **event_fields):
        event = self._new_event(**event_fields)
        evidence = self.backend.create_event(event)
        accepted = isinstance(evidence, dict) and bool(evidence.get("accepted"))
        observed = self.get(evidence.get("event_id")) if accepted and evidence.get("event_id") else None
        verified = accepted and observed is not None and observed["version"] == evidence.get("version")
        return {"status": "verified" if verified else "verification_failed", "accepted": accepted, "verified": verified, "event": observed, "evidence": evidence}

    def update(self, event_id, expected_version, patch):
        event_id = self._text(event_id, "event id", 256)
        expected_version = self._text(expected_version, "expected_version", 256)
        if not isinstance(patch, dict) or not patch:
            raise CalendarError("patch must be a non-empty object")
        allowed = {"title", "start", "end", "timezone", "attendees", "recurrence", "reminders"}
        if set(patch) - allowed:
            raise CalendarError("patch contains unsupported fields")
        current = self.get(event_id)
        if current is None:
            raise CalendarError("event does not exist")
        merged = dict(current)
        merged.update(patch)
        self._event(merged)
        evidence = self.backend.update_event(event_id, expected_version, patch)
        accepted = isinstance(evidence, dict) and bool(evidence.get("accepted"))
        observed = self.get(event_id) if accepted else current
        verified = accepted and observed is not None and observed["version"] == evidence.get("version")
        return {"status": "verified" if verified else "verification_failed", "accepted": accepted, "verified": verified, "event": observed, "evidence": evidence}

    def delete(self, event_id, expected_version):
        event_id = self._text(event_id, "event id", 256)
        expected_version = self._text(expected_version, "expected_version", 256)
        evidence = self.backend.delete_event(event_id, expected_version)
        accepted = isinstance(evidence, dict) and bool(evidence.get("accepted"))
        verified = accepted and self.backend.get_event(event_id) is None
        return {"status": "verified" if verified else "verification_failed", "accepted": accepted, "verified": verified, "event_id": event_id, "evidence": evidence}
