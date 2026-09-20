"""Configuration for zara-knowledge providers."""

from __future__ import annotations

import math
import os
import stat
from dataclasses import dataclass, field
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


def _path(source: Mapping[str, Any], key: str, default: Path) -> Path:
    value = source.get(key, default)
    if not isinstance(value, (str, os.PathLike)):
        raise KnowledgeConfigError(f"{key} must be a path string")
    return Path(value).expanduser()


def _gate_list(source: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = source.get(key, ())
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        raise KnowledgeConfigError(f"{key} must be a string or list of strings")
    result: list[str] = []
    for item in values:
        if not isinstance(item, str) or not item.strip():
            raise KnowledgeConfigError(f"{key} must contain non-empty strings")
        normalized = item.strip().lower()
        if normalized not in result:
            result.append(normalized)
    return tuple(result)


def _gate_mapping(source: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    value = source.get("wiki_gates", {})
    if not isinstance(value, Mapping):
        raise KnowledgeConfigError("wiki_gates must be a mapping")
    result: dict[str, Mapping[str, Any]] = {}
    for gate_id, raw in value.items():
        if not isinstance(gate_id, str) or not gate_id.strip():
            raise KnowledgeConfigError("wiki_gates keys must be non-empty strings")
        if not isinstance(raw, Mapping):
            raise KnowledgeConfigError(f"wiki gate {gate_id!r} must be a mapping")
        result[gate_id.strip().lower()] = dict(raw)
    return result


def _default_store_path() -> Path:
    configured = os.environ.get("XDG_DATA_HOME")
    root = Path(configured).expanduser() if configured else Path.home() / ".local" / "share"
    return root / "zarathushtra" / "zara-knowledge" / "wiki.sqlite3"


@dataclass(frozen=True)
class KnowledgeConfig:
    default_provider: str = "brave"
    brave_api_key: str = ""
    brave_api_key_file: Path | None = None
    timeout_seconds: float = 10.0
    max_response_bytes: int = 2 * 1024 * 1024
    max_results: int = 10
    wiki_store_path: Path = field(default_factory=_default_store_path)
    wiki_max_gates: int = 4
    wiki_default_gates: tuple[str, ...] = ()
    wiki_gates: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

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
            wiki_store_path=_path(source, "wiki_store_path", _default_store_path()),
            wiki_max_gates=_integer(source, "wiki_max_gates", 4),
            wiki_default_gates=_gate_list(source, "wiki_default_gates"),
            wiki_gates=_gate_mapping(source),
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
        if not 1 <= self.wiki_max_gates <= 16:
            raise KnowledgeConfigError("wiki_max_gates must be between 1 and 16")
