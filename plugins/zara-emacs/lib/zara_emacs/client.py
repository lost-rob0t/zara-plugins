"""Bounded Emacs IPC with fixed operation templates."""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Callable

from .config import EmacsConfig


class EmacsError(RuntimeError):
    pass


class EmacsClient:
    def __init__(self, config: EmacsConfig, *, runner: Callable | None = None) -> None:
        config.validate()
        self.config = config
        self._runner = runner or subprocess.run

    def _run(self, argv: list[str]) -> str:
        try:
            result = self._runner(
                argv,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise EmacsError("Emacs client/server unavailable") from error
        if result.returncode != 0:
            detail = str(result.stderr or "Emacs operation failed").strip()[:512]
            raise EmacsError(detail)
        return str(result.stdout or "").strip()[:8192]

    def _eval(self, expression: str) -> str:
        return self._run(
            [
                self.config.emacsclient,
                "--socket-name",
                self.config.server_name,
                "--alternate-editor=false",
                "--eval",
                expression,
            ]
        )

    def open_file(self, path: str) -> dict:
        resolved = Path(str(path)).expanduser()
        if not resolved.is_absolute() or "\x00" in str(resolved):
            raise EmacsError("file path must be an absolute path")
        self._run(
            [
                self.config.emacsclient,
                "--socket-name",
                self.config.server_name,
                "--alternate-editor=false",
                "--no-wait",
                "--",
                str(resolved),
            ]
        )
        return {"operation": "open_file", "path": str(resolved), "acknowledged": True}

    def open_scratch(self) -> dict:
        self._eval('(progn (switch-to-buffer "*scratch*") (buffer-name))')
        return {"operation": "open_scratch", "buffer": "*scratch*", "acknowledged": True}

    def open_buffer(self, name: str) -> dict:
        if not isinstance(name, str) or not name or len(name) > 256 or "\x00" in name:
            raise EmacsError("buffer name is invalid")
        expression = f"(progn (switch-to-buffer {json.dumps(name)}) (buffer-name))"
        self._eval(expression)
        return {"operation": "open_buffer", "buffer": name, "acknowledged": True}

    def open_daily(self, day: str = "today") -> dict:
        value = date.today().isoformat() if day == "today" else str(day)
        try:
            date.fromisoformat(value)
        except ValueError as error:
            raise EmacsError("daily date must be ISO YYYY-MM-DD or today") from error
        encoded = json.dumps(value)
        expression = (
            "(progn (require 'org-roam-dailies) "
            f"(org-roam-dailies--capture (org-read-date nil t {encoded}) t nil) "
            "(or (buffer-file-name) (buffer-name)))"
        )
        observed = self._eval(expression)
        return {
            "operation": "open_daily",
            "date": value,
            "observed": observed,
            "acknowledged": True,
            "post_open": {"request": "dictation", "started": False},
        }

    def open_magit(self, project_id: str) -> dict:
        if project_id not in self.config.projects:
            raise EmacsError(f"unknown project alias: {project_id}")
        path = str(Path(self.config.projects[project_id]).expanduser())
        expression = (
            "(progn (require 'magit) "
            f"(magit-status {json.dumps(path)}) t)"
        )
        self._eval(expression)
        return {
            "operation": "open_magit",
            "project_id": project_id,
            "acknowledged": True,
        }

    def context(self) -> dict:
        expression = (
            "(let ((file (buffer-file-name)) (buffer (buffer-name)) "
            "(project (when (fboundp 'project-current) (project-current nil)))) "
            "(prin1-to-string (list :buffer buffer :file file :project "
            "(when project (car (project-roots project))))))"
        )
        observed = self._eval(expression)
        return {"operation": "context", "observed": observed, "acknowledged": True}
