from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading


AUDIT_FILENAME = "moderation-audit.jsonl"
MAX_REASON_CHARS = 256
DEFAULT_MAX_BYTES = 256 * 1024
DEFAULT_MAX_FILES = 3
_ALLOWED_ACTIONS = frozenset({"inspect", "delete", "warn", "timeout", "kick", "ban"})
_ALLOWED_OUTCOMES = frozenset({"attempted", "succeeded", "failed", "refused"})


def state_directory() -> Path:
    xdg_root = os.environ.get("XDG_STATE_HOME")
    root = Path(xdg_root).expanduser() if xdg_root else Path.home() / ".local" / "state"
    return root / "zarathushtra" / "plugins" / "zara-discord"


class ModerationAudit:
    def __init__(
        self,
        directory: Path | None = None,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_files: int = DEFAULT_MAX_FILES,
    ) -> None:
        self.directory = directory or state_directory()
        self.path = self.directory / AUDIT_FILENAME
        self.max_bytes = max(1, int(max_bytes))
        self.max_files = max(1, int(max_files))
        self._lock = threading.RLock()

    def record(
        self,
        *,
        guild_id: int,
        channel_id: int,
        message_id: int,
        target_id: int,
        action: str,
        outcome: str,
        reason: str,
    ) -> None:
        identifiers = {
            "guild_id": guild_id,
            "channel_id": channel_id,
            "message_id": message_id,
            "target_id": target_id,
        }
        normalized_ids = {}
        for name, value in identifiers.items():
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer Discord ID")
            normalized_ids[name] = value

        normalized_action = str(action).strip().lower()
        if normalized_action not in _ALLOWED_ACTIONS:
            raise ValueError(f"unsupported moderation action: {action!r}")
        normalized_outcome = str(outcome).strip().lower()
        if normalized_outcome not in _ALLOWED_OUTCOMES:
            raise ValueError(f"unsupported moderation outcome: {outcome!r}")

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **normalized_ids,
            "action": normalized_action,
            "outcome": normalized_outcome,
            "actor": "mara",
            "reason": self._sanitize_reason(reason),
        }
        line = (json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        if len(line) > self.max_bytes:
            raise ValueError("moderation audit entry exceeds configured file bound")

        with self._lock:
            self._prepare_directory()
            current_size = self.path.stat().st_size if self.path.exists() else 0
            if current_size and current_size + len(line) > self.max_bytes:
                self._rotate()
            descriptor = os.open(
                self.path,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o600,
            )
            with os.fdopen(descriptor, "ab") as output:
                output.write(line)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(self.path, 0o600)

    def _prepare_directory(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)

    def _rotate(self) -> None:
        if self.max_files <= 1:
            self.path.unlink(missing_ok=True)
            return

        oldest = self.path.with_name(f"{self.path.name}.{self.max_files - 1}")
        oldest.unlink(missing_ok=True)
        for index in range(self.max_files - 2, 0, -1):
            source = self.path.with_name(f"{self.path.name}.{index}")
            if source.exists():
                destination = self.path.with_name(f"{self.path.name}.{index + 1}")
                os.replace(source, destination)
                os.chmod(destination, 0o600)
        if self.path.exists():
            destination = self.path.with_name(f"{self.path.name}.1")
            os.replace(self.path, destination)
            os.chmod(destination, 0o600)

    @staticmethod
    def _sanitize_reason(reason: str) -> str:
        text = "".join(
            character
            for character in str(reason or "")
            if character.isprintable() or character.isspace()
        )
        text = " ".join(text.split())
        return text[:MAX_REASON_CHARS]
