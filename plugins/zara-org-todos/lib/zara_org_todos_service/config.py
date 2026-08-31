from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


DEFAULT_REMOTE = "git@github.com:lost-rob0t/gpt-todos.git"
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


@dataclass(frozen=True)
class OrgTodosConfig:
    repo_dir: Path
    org_dir: Path
    remote: str
    interval_seconds: int
    auto_sync: bool
    timeout_seconds: int

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "OrgTodosConfig":
        home = Path.home()
        repo_value = os.environ.get(
            "ZARA_ORG_TODOS_REPO_DIR",
            values.get("repo_dir", home / "Documents" / "gpt-todos"),
        )
        org_value = os.environ.get(
            "ZARA_ORG_TODOS_ORG_DIR",
            values.get("org_dir", home / "Documents" / "Notes" / "org" / "agenda"),
        )
        remote = str(
            os.environ.get(
                "ZARA_ORG_TODOS_REMOTE",
                values.get("remote", DEFAULT_REMOTE),
            )
        ).strip()
        if not remote:
            raise ValueError("remote must not be empty")

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
            values.get("auto_sync", True),
        )
        auto_sync = _parse_bool(auto_raw, name="auto_sync")

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
            repo_dir=_path(repo_value),
            org_dir=_path(org_value),
            remote=remote,
            interval_seconds=interval,
            auto_sync=auto_sync,
            timeout_seconds=timeout,
        )
