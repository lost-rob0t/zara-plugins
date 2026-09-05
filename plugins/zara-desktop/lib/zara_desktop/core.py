"""Structured desktop domain independent of compositor/backend details."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Protocol, Sequence


class DesktopError(RuntimeError):
    pass


class FeatureUnavailable(DesktopError):
    def __init__(self, feature: str, *, backend: str) -> None:
        self.feature = feature
        self.backend = backend
        super().__init__(f"desktop feature {feature!r} is unavailable on backend {backend!r}")


@dataclass(frozen=True)
class DesktopEvent:
    type: str
    data: dict[str, Any]
    source: str
    timestamp: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class DesktopBackend(Protocol):
    name: str

    def capabilities(self) -> dict[str, bool]: ...
    def launch(self, argv: Sequence[str]) -> dict[str, Any]: ...
    def list_windows(self) -> list[dict[str, Any]]: ...
    def focus_window(self, window_id: str) -> dict[str, Any]: ...
    def close_window(self, window_id: str) -> dict[str, Any]: ...
    def list_workspaces(self) -> list[dict[str, Any]]: ...
    def switch_workspace(self, workspace_id: str) -> dict[str, Any]: ...
    def clipboard_get(self) -> str: ...
    def clipboard_set(self, text: str) -> dict[str, Any]: ...
    def screenshot(self) -> dict[str, Any]: ...
    def poll_events(self, limit: int) -> list[DesktopEvent]: ...


class DesktopController:
    def __init__(
        self,
        backend: DesktopBackend,
        *,
        applications: Mapping[str, Sequence[str]] | None = None,
        max_text_bytes: int = 262144,
        max_events: int = 64,
    ) -> None:
        self.backend = backend
        self.applications = {
            str(alias): tuple(str(part) for part in argv)
            for alias, argv in dict(applications or {}).items()
        }
        self.max_text_bytes = int(max_text_bytes)
        self.max_events = int(max_events)
        if not 1 <= self.max_text_bytes <= 4 * 1024 * 1024:
            raise DesktopError("max_text_bytes is out of range")
        if not 1 <= self.max_events <= 1024:
            raise DesktopError("max_events is out of range")
        for alias, argv in self.applications.items():
            if not alias or len(alias) > 128 or not argv or len(argv) > 32:
                raise DesktopError("application alias configuration is invalid")
            if any(not part or "\x00" in part or len(part) > 4096 for part in argv):
                raise DesktopError("application argv configuration is invalid")

    def status(self) -> dict[str, Any]:
        return {
            "backend": self.backend.name,
            "capabilities": dict(self.backend.capabilities()),
            "applications": sorted(self.applications),
        }

    def launch(self, application_id: str) -> dict[str, Any]:
        if application_id not in self.applications:
            raise DesktopError(f"unknown application alias: {application_id}")
        observed = self.backend.launch(self.applications[application_id])
        return {
            "operation": "launch",
            "application_id": application_id,
            "backend": self.backend.name,
            "observed": observed,
        }

    def windows(self) -> dict[str, Any]:
        return {"backend": self.backend.name, "windows": self.backend.list_windows()[:256]}

    def focus_window(self, window_id: str) -> dict[str, Any]:
        return {"operation": "focus_window", "observed": self.backend.focus_window(self._id(window_id))}

    def close_window(self, window_id: str) -> dict[str, Any]:
        return {"operation": "close_window", "observed": self.backend.close_window(self._id(window_id))}

    def workspaces(self) -> dict[str, Any]:
        return {"backend": self.backend.name, "workspaces": self.backend.list_workspaces()[:128]}

    def switch_workspace(self, workspace_id: str) -> dict[str, Any]:
        return {"operation": "switch_workspace", "observed": self.backend.switch_workspace(self._id(workspace_id))}

    def clipboard_get(self) -> dict[str, Any]:
        text = self.backend.clipboard_get()
        encoded = text.encode("utf-8")
        if len(encoded) > self.max_text_bytes:
            raise DesktopError("clipboard content is too large")
        return {"text": text, "bytes": len(encoded), "source": self.backend.name}

    def clipboard_set(self, text: str) -> dict[str, Any]:
        if not isinstance(text, str):
            raise DesktopError("clipboard content must be text")
        encoded = text.encode("utf-8")
        if len(encoded) > self.max_text_bytes:
            raise DesktopError("clipboard content is too large")
        return {"operation": "clipboard_set", "observed": self.backend.clipboard_set(text)}

    def screenshot(self) -> dict[str, Any]:
        observed = self.backend.screenshot()
        return {"operation": "screenshot", "observed": observed}

    def events(self, *, limit: int = 20) -> dict[str, Any]:
        count = min(max(int(limit), 1), self.max_events)
        events = self.backend.poll_events(count)
        return {"events": [event.as_dict() for event in events[:count]]}

    @staticmethod
    def _id(value: str) -> str:
        text = str(value)
        if not text or len(text) > 256 or "\x00" in text:
            raise DesktopError("desktop object identifier is invalid")
        return text
