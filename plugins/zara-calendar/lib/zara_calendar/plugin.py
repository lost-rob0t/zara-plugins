from __future__ import annotations

import json

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .domain import CalendarDomain, CalendarError


PLUGIN_VERSION = "0.1.0"


class UnavailableCalendarBackend:
    reason = "calendar-backend-not-configured"

    def __getattr__(self, name):
        raise CalendarError(self.reason)


class ZaraCalendarPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-calendar",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Provider-neutral calendar search, free-busy, scheduling, and verified mutations",
    )

    def __init__(self, backend=None) -> None:
        self.backend = backend or UnavailableCalendarBackend()
        self.domain = CalendarDomain(self.backend)

    def start(self, runtime) -> None:
        return None

    def stop(self) -> None:
        return None

    @staticmethod
    def _json(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def status(self) -> str:
        if isinstance(self.backend, UnavailableCalendarBackend):
            return self._json({"status": "unavailable", "reason": self.backend.reason})
        return self._json({"status": "ready"})

    def search(self, start: str, end: str, text: str = "", calendar_id: str = "", limit: int = 50) -> str:
        return self._json(self.domain.search(start, end, text=text or None, calendar_id=calendar_id or None, limit=limit))

    def get(self, event_id: str) -> str:
        return self._json(self.domain.get(event_id))

    def free_busy(self, start: str, end: str, calendar_ids: list[str]) -> str:
        return self._json(self.domain.free_busy(start, end, calendar_ids))

    def conflicts(self, start: str, end: str, calendar_ids: list[str]) -> str:
        return self._json(self.domain.explain_conflicts(start, end, calendar_ids))

    def suggest(self, start: str, end: str, duration_minutes: int, calendar_ids: list[str], step_minutes: int = 30) -> str:
        return self._json(self.domain.suggest_times(start, end, duration_minutes=duration_minutes, calendar_ids=calendar_ids, step_minutes=step_minutes))

    def create(self, calendar_id: str, title: str, start: str, end: str, timezone_name: str, attendees: list[str], reminders: list[dict], recurrence: dict | None = None) -> str:
        return self._json(self.domain.create(calendar_id=calendar_id, title=title, start=start, end=end, timezone_name=timezone_name, attendees=attendees, recurrence=recurrence, reminders=reminders))

    def update(self, event_id: str, expected_version: str, patch: dict) -> str:
        return self._json(self.domain.update(event_id, expected_version, patch))

    def delete(self, event_id: str, expected_version: str) -> str:
        return self._json(self.domain.delete(event_id, expected_version))

    def tools(self):
        return (
            StructuredTool.from_function(func=self.status, name="calendar.status", description="Report whether a calendar backend is configured."),
            StructuredTool.from_function(func=self.search, name="calendar.search", description="Search bounded timezone-aware calendar windows."),
            StructuredTool.from_function(func=self.get, name="calendar.get", description="Read one normalized calendar event."),
            StructuredTool.from_function(func=self.free_busy, name="calendar.free_busy", description="Return bounded busy intervals for explicit calendars."),
            StructuredTool.from_function(func=self.conflicts, name="calendar.conflicts", description="Explain conflicts for one candidate interval."),
            StructuredTool.from_function(func=self.suggest, name="calendar.suggest", description="Return read-only candidate times without writing events."),
            StructuredTool.from_function(func=self.create, name="calendar.create", description="Create an event explicitly and verify provider-observed state."),
            StructuredTool.from_function(func=self.update, name="calendar.update", description="Update an event with expected-version protection and verification."),
            StructuredTool.from_function(func=self.delete, name="calendar.delete", description="Delete an event with expected-version protection and verify absence."),
        )


def create_plugin():
    return ZaraCalendarPlugin()
