"""Configuration for zara-desktop."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .core import DesktopError


@dataclass(frozen=True)
class DesktopConfig:
    applications: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    max_text_bytes: int = 262144
    max_events: int = 64

    @classmethod
    def load(cls, mapping: Mapping[str, Any] | None) -> "DesktopConfig":
        source = dict(mapping or {})
        raw_apps = source.get("applications", {})
        if not isinstance(raw_apps, Mapping):
            raise DesktopError("applications must be an alias-to-argv mapping")
        applications: dict[str, tuple[str, ...]] = {}
        for alias, command in raw_apps.items():
            if not isinstance(command, Sequence) or isinstance(command, (str, bytes)):
                raise DesktopError(f"application {alias!r} must be an argv list")
            applications[str(alias)] = tuple(str(part) for part in command)
        return cls(
            applications=applications,
            max_text_bytes=int(source.get("max_text_bytes", 262144)),
            max_events=int(source.get("max_events", 64)),
        )
