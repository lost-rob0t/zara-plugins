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
    notes_root: str = "~/Documents/Notes/org"
    projects: Mapping[str, str] = field(default_factory=dict)
    commands: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, mapping: Mapping[str, Any] | None) -> "EmacsConfig":
        source = dict(mapping or {})
        emacsclient = source.get("emacsclient", "emacsclient")
        server_name = source.get("server_name", "server")
        timeout_seconds = source.get("timeout_seconds", 10.0)
        notes_root = source.get("notes_root", "~/Documents/Notes/org")
        raw_projects = source.get("projects", {})
        raw_commands = source.get("commands", {})
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
        if not isinstance(notes_root, str):
            raise EmacsConfigError("notes_root must be a string")
        if not isinstance(raw_projects, Mapping):
            raise EmacsConfigError("projects must be an alias-to-path mapping")
        if not isinstance(raw_commands, Mapping):
            raise EmacsConfigError("commands must be an alias-to-command mapping")
        projects: dict[str, str] = {}
        for alias, path in raw_projects.items():
            if not isinstance(alias, str) or not isinstance(path, str):
                raise EmacsConfigError("project aliases and paths must be strings")
            projects[alias] = path
        commands: dict[str, str] = {}
        for alias, command in raw_commands.items():
            if not isinstance(alias, str) or not isinstance(command, str):
                raise EmacsConfigError("command aliases and command names must be strings")
            commands[alias] = command
        config = cls(
            emacsclient=emacsclient,
            server_name=server_name,
            timeout_seconds=float(timeout_seconds),
            notes_root=notes_root,
            projects=projects,
            commands=commands,
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
        notes_root = Path(self.notes_root).expanduser()
        if not notes_root.is_absolute() or "\\x00" in self.notes_root:
            raise EmacsConfigError("notes_root must be an absolute path")
        if not isinstance(self.projects, Mapping):
            raise EmacsConfigError("projects must be an alias-to-path mapping")
        for alias, path in self.projects.items():
            if not isinstance(alias, str) or not isinstance(path, str):
                raise EmacsConfigError("project aliases and paths must be strings")
            if not alias or len(alias) > 128:
                raise EmacsConfigError("project aliases must contain 1 to 128 characters")
            if not Path(path).expanduser().is_absolute():
                raise EmacsConfigError(f"project {alias!r} must map to an absolute path")
        if not isinstance(self.commands, Mapping):
            raise EmacsConfigError("commands must be an alias-to-command mapping")
        for alias, command in self.commands.items():
            if not isinstance(alias, str) or not isinstance(command, str):
                raise EmacsConfigError("command aliases and command names must be strings")
            if not alias or len(alias) > 128 or any(ch.isspace() for ch in alias):
                raise EmacsConfigError("command aliases must contain 1 to 128 non-whitespace characters")
            if not command or len(command) > 256 or any(ch in command for ch in ("\\x00", "\\n", "\\r")):
                raise EmacsConfigError("Emacs command names must contain 1 to 256 single-line characters")
