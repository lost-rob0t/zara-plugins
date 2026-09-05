"""Structured desktop domain independent of compositor/backend details."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Protocol, Sequence


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
    def launch(self, app: str, args: Sequence[str]) -> dict[str, Any]: ...
    def list_windows(self) -> list[dict[str, Any]]: ...
    def focus_window(self, window_id: str) -> dict[str, Any]: ...
    def close_window(self, window_id: str) -> dict[str, Any]: ...
    def list_workspaces(self) -> list[dict[str, Any]]: ...
    def switch_workspace(self, workspace_id: str) -> dict[str, Any]: ...
    def clipboard_get(self) -> str: ...
    def clipboard_set(self, text: str) -> dict[str, Any]: ...
    def screenshot(self) -> dict[str, Any]: ...
    def poll_events(self, limit: int) -> list[DesktopEvent]: ...


_SAFE_APP = re.compile(r"^[A-Za-z0-9._+-]{1,128}$")


class DesktopController:
    def __init__(self, backend: DesktopBackend, *, max_text_bytes: int = 262144, max_events: int = 64) -> None:
        self.backend = backend
        self.max_text_bytes = int(max_text_bytes)
        self.max_events = int(max_events)
        if not 1 <= self.max_text_bytes <= 4 * 1024 * 1024:
            raise DesktopError("max_text_bytes is out of range")
        if not 1 <= self.max_events <= 1024:
            raise DesktopError("max_events is out of range")

    def status(self) -> dict[str, Any]:
        return {"backend": self.backend.name, "capabilities": dict(self.backend.capabilities())}

    def launch(self, app: str, args: Sequence[str] = ()) -> dict[str, Any]:
        if not isinstance(app, str) or not _SAFE_APP.fullmatch(app):
            raise DesktopError("application must be a simple executable identifier")
        argv = [str(arg) for arg in args]
        if len(argv) > 32 or any("\x00" in arg or len(arg) > 4096 for arg in argv):
            raise DesktopError("application arguments exceed configured bounds")
        observed = self.backend.launch(app, argv)
        return {"operation": "launch", "backend": self.backend.name, "observed": observed}

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
