"""Configuration for zara-emacs."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


class EmacsConfigError(ValueError):
    pass


@dataclass(frozen=True)
class EmacsConfig:
    emacsclient: str = "emacsclient"
    server_name: str = "server"
    timeout_seconds: float = 10.0
    projects: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, mapping: Mapping[str, Any] | None) -> "EmacsConfig":
        source = dict(mapping or {})
        emacsclient = source.get("emacsclient", "emacsclient")
        server_name = source.get("server_name", "server")
        timeout_seconds = source.get("timeout_seconds", 10.0)
        raw_projects = source.get("projects", {})
        if not isinstance(emacsclient, str):
            raise EmacsConfigError("emacsclient must be a string")
        if not isinstance(server_name, str):
            raise EmacsConfigError("server_name must be a string")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
        ):
            raise EmacsConfigError("timeout_seconds must be a finite number")
        if not isinstance(raw_projects, Mapping):
            raise EmacsConfigError("projects must be an alias-to-path mapping")
        projects: dict[str, str] = {}
        for alias, path in raw_projects.items():
            if not isinstance(alias, str) or not isinstance(path, str):
                raise EmacsConfigError("project aliases and paths must be strings")
            projects[alias] = path
        config = cls(
            emacsclient=emacsclient,
            server_name=server_name,
            timeout_seconds=float(timeout_seconds),
            projects=projects,
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not isinstance(self.emacsclient, str) or not self.emacsclient or "/" in self.emacsclient:
            raise EmacsConfigError("emacsclient must be a command name, not a path or shell fragment")
        if (
            not isinstance(self.server_name, str)
            or not self.server_name
            or len(self.server_name) > 128
            or any(ch.isspace() for ch in self.server_name)
        ):
            raise EmacsConfigError("server_name is invalid")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or not 0.1 <= self.timeout_seconds <= 60
        ):
            raise EmacsConfigError("timeout_seconds must be between 0.1 and 60")
        if not isinstance(self.projects, Mapping):
            raise EmacsConfigError("projects must be an alias-to-path mapping")
        for alias, path in self.projects.items():
            if not isinstance(alias, str) or not isinstance(path, str):
                raise EmacsConfigError("project aliases and paths must be strings")
            if not alias or len(alias) > 128:
                raise EmacsConfigError("project aliases must contain 1 to 128 characters")
            if not Path(path).expanduser().is_absolute():
                raise EmacsConfigError(f"project {alias!r} must map to an absolute path")
