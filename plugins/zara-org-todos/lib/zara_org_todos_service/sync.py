from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .config import OrgTodosConfig


SYNC_SOURCE_COMMIT = "7b88a3c2ddef7f3fffc09fd049476e06cf13d93a"
MAX_OUTPUT = 8192


class SyncError(RuntimeError):
    pass


class SyncBusyError(SyncError):
    pass


@dataclass(frozen=True)
class SyncResult:
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float

    @property
    def summary(self) -> str:
        output = self.stdout.strip() or self.stderr.strip()
        return output[-MAX_OUTPUT:] if output else "sync completed"


def bundled_script_path() -> Path:
    return Path(__file__).resolve().parents[2] / "libexec" / "gpt-todos-sync"


class SyncRunner:
    def __init__(
        self,
        config: OrgTodosConfig,
        *,
        script_path: Optional[Path] = None,
        run_process: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.config = config
        self.script_path = script_path or bundled_script_path()
        self._run_process = run_process
        self._lock = threading.Lock()

    def run(self, *, saved_file: Optional[Path] = None) -> SyncResult:
        if not self._lock.acquire(blocking=False):
            raise SyncBusyError("Org todo sync is already running")
        started = time.monotonic()
        try:
            if not self.script_path.is_file():
                raise SyncError(f"bundled sync script not found: {self.script_path}")
            command = ["bash", str(self.script_path)]
            if saved_file is not None:
                command.extend(("--file", str(saved_file.expanduser())))
            environment = os.environ.copy()
            environment.update(
                {
                    "GPT_TODOS_REPO_DIR": str(self.config.repo_dir),
                    "GPT_TODOS_ORG_DIR": str(self.config.org_dir),
                    "GPT_TODOS_REMOTE": self.config.remote,
                    "GIT_TERMINAL_PROMPT": "0",
                    "DOTFILES_DIR": str(
                        Path(environment.get("XDG_RUNTIME_DIR", "/tmp"))
                        / f"zara-org-todos-no-dotfiles-{os.getuid()}"
                    ),
                }
            )
            try:
                completed = self._run_process(
                    command,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=self.config.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise SyncError(
                    f"Org todo sync exceeded {self.config.timeout_seconds} seconds"
                ) from error
            duration = time.monotonic() - started
            result = SyncResult(
                returncode=completed.returncode,
                stdout=(completed.stdout or "")[-MAX_OUTPUT:],
                stderr=(completed.stderr or "")[-MAX_OUTPUT:],
                duration_seconds=duration,
            )
            if completed.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
                raise SyncError(f"Org todo sync failed ({completed.returncode}): {detail}")
            return result
        finally:
            self._lock.release()
