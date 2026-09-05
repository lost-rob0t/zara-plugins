from __future__ import annotations

import base64
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence


MAX_CLIPBOARD_BYTES = 16 * 1024
MAX_SCREENSHOT_BYTES = 4 * 1024 * 1024
MAX_APPLICATIONS = 64
COMMAND_TIMEOUT_SECONDS = 5.0


class DesktopError(RuntimeError):
    pass


@dataclass(frozen=True)
class DesktopConfig:
    applications: Mapping[str, tuple[str, ...]]

    @classmethod
    def load(cls, configuration: object) -> "DesktopConfig":
        section: object = {}
        if isinstance(configuration, Mapping):
            plugins = configuration.get("plugins")
            if isinstance(plugins, Mapping):
                section = plugins.get("zara-desktop", {})
            elif "applications" in configuration:
                section = configuration
        raw = section.get("applications", {}) if isinstance(section, Mapping) else {}
        if not isinstance(raw, Mapping) or len(raw) > MAX_APPLICATIONS:
            raise DesktopError("desktop applications must be a bounded mapping")
        applications: dict[str, tuple[str, ...]] = {}
        for alias, argv in raw.items():
            if not isinstance(alias, str) or not alias or len(alias) > 64:
                raise DesktopError("desktop application alias is invalid")
            if not isinstance(argv, Sequence) or isinstance(argv, (str, bytes)):
                raise DesktopError(f"desktop application {alias!r} must be an argv list")
            command = tuple(argv)
            if not command or len(command) > 16 or any(not isinstance(item, str) or not item or len(item) > 1024 for item in command):
                raise DesktopError(f"desktop application {alias!r} has invalid argv")
            applications[alias] = command
        return cls(applications=applications)


class SystemDesktopBackend:
    def __init__(self, *, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> None:
        self._runner = runner

    @staticmethod
    def capabilities() -> dict[str, bool]:
        return {
            "launch": True,
            "clipboard_read": shutil.which("wl-paste") is not None,
            "clipboard_write": shutil.which("wl-copy") is not None,
            "screenshot": shutil.which("grim") is not None,
            "windows": shutil.which("wmctrl") is not None,
            "workspaces": shutil.which("wmctrl") is not None,
        }

    def launch(self, argv: Sequence[str]) -> dict[str, object]:
        try:
            process = subprocess.Popen(
                list(argv),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                start_new_session=True,
            )
        except OSError as error:
            return {"status": "unavailable", "acknowledged": False, "reason": type(error).__name__}
        return {"status": "ok", "acknowledged": True, "pid": process.pid}

    def clipboard_read(self) -> dict[str, object]:
        if shutil.which("wl-paste") is None:
            return {"status": "unavailable", "reason": "clipboard-backend-unavailable"}
        result = self._runner(
            ["wl-paste", "--no-newline"],
            capture_output=True,
            text=False,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
        data = bytes(result.stdout or b"")
        if result.returncode != 0:
            return {"status": "unavailable", "reason": "clipboard-read-failed"}
        if len(data) > MAX_CLIPBOARD_BYTES:
            raise DesktopError("clipboard content exceeds byte limit")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return {"status": "ok", "kind": "binary", "size": len(data), "content": None}
        return {"status": "ok", "kind": "text", "size": len(data), "content": text}

    def clipboard_write(self, text: str) -> dict[str, object]:
        if not isinstance(text, str):
            raise DesktopError("clipboard text must be a string")
        encoded = text.encode("utf-8")
        if len(encoded) > MAX_CLIPBOARD_BYTES:
            raise DesktopError("clipboard content exceeds byte limit")
        if shutil.which("wl-copy") is None:
            return {"status": "unavailable", "reason": "clipboard-backend-unavailable"}
        result = self._runner(
            ["wl-copy"],
            input=encoded,
            capture_output=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
        return {"status": "ok", "acknowledged": True} if result.returncode == 0 else {"status": "unavailable", "acknowledged": False, "reason": "clipboard-write-failed"}

    def screenshot(self) -> dict[str, object]:
        if shutil.which("grim") is None:
            return {"status": "unavailable", "reason": "screenshot-backend-unavailable"}
        result = self._runner(
            ["grim", "-"],
            capture_output=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
        data = bytes(result.stdout or b"")
        if result.returncode != 0:
            return {"status": "unavailable", "reason": "screenshot-failed"}
        if len(data) > MAX_SCREENSHOT_BYTES:
            raise DesktopError("screenshot exceeds byte limit")
        return {"status": "ok", "mime_type": "image/png", "size": len(data), "data_base64": base64.b64encode(data).decode("ascii")}

    def windows(self) -> dict[str, object]:
        return {"status": "unavailable", "reason": "window-backend-not-configured"}

    def workspaces(self) -> dict[str, object]:
        return {"status": "unavailable", "reason": "workspace-backend-not-configured"}


class DesktopService:
    def __init__(self, config: DesktopConfig | None = None, backend: SystemDesktopBackend | None = None) -> None:
        self.config = config or DesktopConfig(applications={})
        self.backend = backend or SystemDesktopBackend()

    def status(self) -> dict[str, object]:
        return {"status": "ok", "backend": "linux", "capabilities": self.backend.capabilities(), "configured_applications": sorted(self.config.applications)}

    def launch(self, application: str) -> dict[str, object]:
        if application not in self.config.applications:
            return {"status": "unavailable", "acknowledged": False, "reason": "unknown-application", "application": application}
        result = self.backend.launch(self.config.applications[application])
        return {**result, "application": application}

    def clipboard_read(self) -> dict[str, object]:
        return self.backend.clipboard_read()

    def clipboard_write(self, text: str) -> dict[str, object]:
        return self.backend.clipboard_write(text)

    def screenshot(self) -> dict[str, object]:
        return self.backend.screenshot()

    def windows(self) -> dict[str, object]:
        return self.backend.windows()

    def workspaces(self) -> dict[str, object]:
        return self.backend.workspaces()
