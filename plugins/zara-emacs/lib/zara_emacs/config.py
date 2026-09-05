"""Configuration for zara-emacs."""

from __future__ import annotations

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
        raw_projects = source.get("projects", {})
        if not isinstance(raw_projects, Mapping):
            raise EmacsConfigError("projects must be an alias-to-path mapping")
        projects = {str(key): str(value) for key, value in raw_projects.items()}
        config = cls(
            emacsclient=str(source.get("emacsclient", "emacsclient")),
            server_name=str(source.get("server_name", "server")),
            timeout_seconds=float(source.get("timeout_seconds", 10.0)),
            projects=projects,
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not self.emacsclient or "/" in self.emacsclient:
            raise EmacsConfigError("emacsclient must be a command name, not a path or shell fragment")
        if not self.server_name or len(self.server_name) > 128 or any(ch.isspace() for ch in self.server_name):
            raise EmacsConfigError("server_name is invalid")
        if not 0.1 <= self.timeout_seconds <= 60:
            raise EmacsConfigError("timeout_seconds must be between 0.1 and 60")
        for alias, path in self.projects.items():
            if not alias or len(alias) > 128:
                raise EmacsConfigError("project aliases must contain 1 to 128 characters")
            if not Path(path).expanduser().is_absolute():
                raise EmacsConfigError(f"project {alias!r} must map to an absolute path")
