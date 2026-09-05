from __future__ import annotations

import json
import os
from pathlib import Path

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .domain import TimerDomain


PLUGIN_VERSION = "0.1.0"


def default_state_path():
    state_home = os.environ.get("XDG_STATE_HOME")
    root = Path(state_home).expanduser() if state_home else Path.home() / ".local" / "state"
    return root / "zara" / "plugins" / "zara-timers" / "timers.json"


class ZaraTimersPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-timers",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Persistent countdown timers, alarms, recurring reminders, and due events",
    )

    def __init__(self, state_path=None, *, clock=None, missed_policy="fire_once"):
        self.domain = TimerDomain(state_path or default_state_path(), clock=clock, missed_policy=missed_policy)

    def start(self, runtime) -> None:
        return None

    def stop(self) -> None:
        return None

    @staticmethod
    def _json(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def create_timer(self, name: str, duration_seconds: float) -> str:
        return self._json(self.domain.create_timer(name, duration_seconds))

    def create_alarm(self, name: str, due_at: str) -> str:
        return self._json(self.domain.create_alarm(name, due_at))

    def create_reminder(self, name: str, due_at: str, cadence_seconds: int, timezone_name: str) -> str:
        return self._json(self.domain.create_reminder(name, due_at, cadence_seconds=cadence_seconds, timezone_name=timezone_name))

    def list_items(self) -> str:
        return self._json(self.domain.list())

    def get(self, timer_id: str) -> str:
        return self._json(self.domain.get(timer_id))

    def pause(self, timer_id: str) -> str:
        return self._json(self.domain.pause(timer_id))

    def resume(self, timer_id: str) -> str:
        return self._json(self.domain.resume(timer_id))

    def cancel(self, timer_id: str) -> str:
        return self._json(self.domain.cancel(timer_id))

    def poll_due(self) -> str:
        return self._json(self.domain.poll_due())

    def drain_events(self) -> str:
        return self._json(self.domain.drain_events())

    def tools(self):
        return (
            StructuredTool.from_function(func=self.create_timer, name="timers.create", description="Create a named monotonic countdown timer."),
            StructuredTool.from_function(func=self.create_alarm, name="timers.alarm", description="Create an absolute timezone-aware alarm."),
            StructuredTool.from_function(func=self.create_reminder, name="timers.reminder", description="Create a recurring timezone-aware reminder."),
            StructuredTool.from_function(func=self.list_items, name="timers.list", description="List timers, alarms, and reminders with countdown state."),
            StructuredTool.from_function(func=self.get, name="timers.get", description="Get one timer, alarm, or reminder by stable ID."),
            StructuredTool.from_function(func=self.pause, name="timers.pause", description="Pause a countdown timer."),
            StructuredTool.from_function(func=self.resume, name="timers.resume", description="Resume a paused countdown timer."),
            StructuredTool.from_function(func=self.cancel, name="timers.cancel", description="Cancel an item and emit a cancellation event."),
            StructuredTool.from_function(func=self.poll_due, name="timers.poll_due", description="Advance due state and return newly fired events."),
            StructuredTool.from_function(func=self.drain_events, name="timers.drain_events", description="Consume queued fired and cancelled timer events."),
        )


def create_plugin():
    return ZaraTimersPlugin()
