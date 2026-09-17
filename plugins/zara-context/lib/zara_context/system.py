from __future__ import annotations

import os
import platform
from typing import Callable, Mapping


MAX_SYSTEM_CONTEXT_CHARS = 2048
_ALLOWED_ENV = (
    ("session_type", "XDG_SESSION_TYPE"),
    ("desktop", "XDG_CURRENT_DESKTOP"),
    ("desktop_session", "DESKTOP_SESSION"),
    ("wayland_display", "WAYLAND_DISPLAY"),
    ("x_display", "DISPLAY"),
)


class LinuxSystemContextProvider:
    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        uname: Callable[[], object] = platform.uname,
    ) -> None:
        self._environ = os.environ if environ is None else environ
        self._uname = uname

    def facts(self) -> tuple[tuple[str, str], ...]:
        uname = self._uname()
        values: list[tuple[str, str]] = []
        for key, value in (
            ("os", getattr(uname, "system", "")),
            ("kernel", getattr(uname, "release", "")),
            ("machine", getattr(uname, "machine", "")),
        ):
            normalized = self._bounded(value)
            if normalized:
                values.append((key, normalized))
        for key, env_name in _ALLOWED_ENV:
            normalized = self._bounded(self._environ.get(env_name, ""))
            if normalized:
                values.append((key, normalized))
        return tuple(values)

    def render(self) -> str:
        rendered = "Linux desktop context:\n" + "\n".join(
            f"{key}={value}" for key, value in self.facts()
        )
        return rendered[:MAX_SYSTEM_CONTEXT_CHARS].rstrip()

    @staticmethod
    def _bounded(value: object) -> str:
        if not isinstance(value, str):
            return ""
        normalized = " ".join(value.strip().split())
        if not normalized or len(normalized) > 256:
            return ""
        if any(ord(character) < 0x20 for character in normalized):
            return ""
        return normalized
