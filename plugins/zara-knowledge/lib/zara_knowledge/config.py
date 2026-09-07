"""Configuration for zara-knowledge providers."""

from __future__ import annotations

import math
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class KnowledgeConfigError(ValueError):
    pass


def _read_secret(path: Path) -> str:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as error:
        raise KnowledgeConfigError(f"cannot read Brave credential file: {error}") from error
    if mode != 0o600:
        raise KnowledgeConfigError("Brave credential file must have mode 0600")
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise KnowledgeConfigError(f"cannot read Brave credential file: {error}") from error


def _string(source: Mapping[str, Any], key: str, default: str) -> str:
    value = source.get(key, default)
    if not isinstance(value, str):
        raise KnowledgeConfigError(f"{key} must be a string")
    return value


def _timeout(source: Mapping[str, Any]) -> float:
    value = source.get("timeout_seconds", 10.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KnowledgeConfigError("timeout_seconds must be a finite number")
    timeout = float(value)
    if not math.isfinite(timeout):
        raise KnowledgeConfigError("timeout_seconds must be a finite number")
    return timeout


def _integer(source: Mapping[str, Any], key: str, default: int) -> int:
    value = source.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise KnowledgeConfigError(f"{key} must be an integer")
    return value


@dataclass(frozen=True)
class KnowledgeConfig:
    default_provider: str = "brave"
    brave_api_key: str = ""
    brave_api_key_file: Path | None = None
    timeout_seconds: float = 10.0
    max_response_bytes: int = 2 * 1024 * 1024
    max_results: int = 10

    @classmethod
    def load(cls, mapping: Mapping[str, Any] | None) -> "KnowledgeConfig":
        source = dict(mapping or {})
        configured_file = source.get("brave_api_key_file")
        if configured_file is not None and not isinstance(configured_file, (str, os.PathLike)):
            raise KnowledgeConfigError("brave_api_key_file must be a path string")
        secret_file = Path(configured_file).expanduser() if configured_file else None

        environment_key = os.environ.get("BRAVE_SEARCH_API_KEY")
        if environment_key is not None:
            key = environment_key.strip()
        else:
            key = _string(source, "brave_api_key", "").strip()
        if not key and secret_file is not None:
            key = _read_secret(secret_file)

        config = cls(
            default_provider=_string(source, "default_provider", "brave").strip().lower(),
            brave_api_key=key,
            brave_api_key_file=secret_file,
            timeout_seconds=_timeout(source),
            max_response_bytes=_integer(source, "max_response_bytes", 2 * 1024 * 1024),
            max_results=_integer(source, "max_results", 10),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.default_provider not in {"brave"}:
            raise KnowledgeConfigError(f"unsupported default_provider {self.default_provider!r}")
        if not 0.1 <= self.timeout_seconds <= 60:
            raise KnowledgeConfigError("timeout_seconds must be between 0.1 and 60")
        if not 1024 <= self.max_response_bytes <= 8 * 1024 * 1024:
            raise KnowledgeConfigError("max_response_bytes must be between 1024 and 8388608")
        if not 1 <= self.max_results <= 20:
            raise KnowledgeConfigError("max_results must be between 1 and 20")
