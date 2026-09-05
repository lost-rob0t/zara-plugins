"""Configuration for zara-knowledge providers."""

from __future__ import annotations

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
        secret_file = Path(str(configured_file)).expanduser() if configured_file else None
        key = str(os.environ.get("BRAVE_SEARCH_API_KEY", source.get("brave_api_key", ""))).strip()
        if not key and secret_file is not None:
            key = _read_secret(secret_file)
        config = cls(
            default_provider=str(source.get("default_provider", "brave")).strip().lower(),
            brave_api_key=key,
            brave_api_key_file=secret_file,
            timeout_seconds=float(source.get("timeout_seconds", 10.0)),
            max_response_bytes=int(source.get("max_response_bytes", 2 * 1024 * 1024)),
            max_results=int(source.get("max_results", 10)),
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
