"""Secret-safe configuration for the Zara GitHub provider."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


class GitHubConfigError(ValueError):
    pass


def _token_from_file(path: Path) -> str:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as error:
        raise GitHubConfigError(f"cannot read token_file: {error}") from error
    if mode != 0o600:
        raise GitHubConfigError("token_file must have mode 0600")
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise GitHubConfigError(f"cannot read token_file: {error}") from error


def _numeric_config(source: dict, key: str, default: int | float, converter):
    value = source.get(key, default)
    if isinstance(value, bool):
        raise GitHubConfigError(f"{key} must not be boolean")
    try:
        return converter(value)
    except (TypeError, ValueError) as error:
        raise GitHubConfigError(f"{key} must be numeric") from error


@dataclass(frozen=True)
class GitHubConfig:
    token: str = ""
    token_file: Path | None = None
    owner: str = ""
    api_base: str = "https://api.github.com"
    timeout_seconds: float = 30.0
    max_response_bytes: int = 2 * 1024 * 1024
    max_results: int = 20

    @classmethod
    def load(cls, mapping: dict | None) -> "GitHubConfig":
        source = dict(mapping or {})
        timeout_seconds = _numeric_config(source, "timeout_seconds", 30.0, float)
        max_response_bytes = _numeric_config(source, "max_response_bytes", 2 * 1024 * 1024, int)
        max_results = _numeric_config(source, "max_results", 20, int)
        xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        configured_file = source.get("token_file")
        token_file = Path(str(configured_file)).expanduser() if configured_file else None
        token = str(os.environ.get("ZARA_GITHUB_TOKEN", source.get("token", ""))).strip()
        if not token and token_file is not None:
            token = _token_from_file(token_file)
        config = cls(
            token=token,
            token_file=token_file,
            owner=str(source.get("owner", os.environ.get("ZARA_GITHUB_OWNER", ""))).strip(),
            api_base=str(source.get("api_base", "https://api.github.com")).strip().rstrip("/"),
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            max_results=max_results,
        )
        config.validate()
        return config

    def validate(self) -> None:
        parsed = urlsplit(self.api_base)
        if parsed.scheme != "https" or not parsed.hostname:
            raise GitHubConfigError("remote GitHub api_base must use https")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise GitHubConfigError("api_base must not contain credentials, query, or fragment")
        if not 0.1 <= self.timeout_seconds <= 120:
            raise GitHubConfigError("timeout_seconds must be between 0.1 and 120")
        if not 1024 <= self.max_response_bytes <= 8 * 1024 * 1024:
            raise GitHubConfigError("max_response_bytes must be between 1024 and 8388608")
        if not 1 <= self.max_results <= 100:
            raise GitHubConfigError("max_results must be between 1 and 100")
