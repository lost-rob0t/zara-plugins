from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional


MIN_INTERVAL_SECONDS = 60


def _parse_bool(value: Any, *, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"{name} must be a boolean")


def _path(value: Any) -> Path:
    return Path(str(value)).expanduser()


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class OrgTodosConfig:
    org_dir: Path
    git_sync: bool
    repo_dir: Path
    remote: Optional[str]
    interval_seconds: int
    auto_sync: bool
    timeout_seconds: int

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "OrgTodosConfig":
        home = Path.home()
        data_home = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))

        org_value = os.environ.get(
            "ZARA_ORG_TODOS_ORG_DIR",
            values.get("org_dir", home / "Documents" / "Notes" / "org" / "agenda"),
        )
        repo_value = os.environ.get(
            "ZARA_ORG_TODOS_REPO_DIR",
            values.get("repo_dir", data_home / "zarathushtra" / "org-todos-git"),
        )
        remote = _optional_text(
            os.environ.get("ZARA_ORG_TODOS_REMOTE", values.get("remote"))
        )

        git_sync_raw = os.environ.get(
            "ZARA_ORG_TODOS_GIT_SYNC",
            values.get("git_sync", False),
        )
        git_sync = _parse_bool(git_sync_raw, name="git_sync")
        if git_sync and remote is None:
            raise ValueError("remote is required when git_sync=true")

        interval_raw = os.environ.get(
            "ZARA_ORG_TODOS_INTERVAL",
            values.get("interval_seconds", 300),
        )
        try:
            interval = int(interval_raw)
        except (TypeError, ValueError) as error:
            raise ValueError("interval_seconds must be an integer") from error
        if interval < MIN_INTERVAL_SECONDS:
            raise ValueError(f"interval_seconds must be at least {MIN_INTERVAL_SECONDS}")

        auto_raw = os.environ.get(
            "ZARA_ORG_TODOS_AUTO_SYNC",
            values.get("auto_sync", False),
        )
        auto_sync = _parse_bool(auto_raw, name="auto_sync")
        if auto_sync and not git_sync:
            raise ValueError("auto_sync requires git_sync=true")

        timeout_raw = os.environ.get(
            "ZARA_ORG_TODOS_TIMEOUT",
            values.get("timeout_seconds", 120),
        )
        try:
            timeout = int(timeout_raw)
        except (TypeError, ValueError) as error:
            raise ValueError("timeout_seconds must be an integer") from error
        if timeout < 5:
            raise ValueError("timeout_seconds must be at least 5")

        return cls(
            org_dir=_path(org_value),
            git_sync=git_sync,
            repo_dir=_path(repo_value),
            remote=remote,
            interval_seconds=interval,
            auto_sync=auto_sync,
            timeout_seconds=timeout,
        )
