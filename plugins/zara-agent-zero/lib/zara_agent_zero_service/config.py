"""Configuration for the Agent Zero native API bridge."""

from __future__ import annotations

import ipaddress
import math
import os
from dataclasses import dataclass
from urllib.parse import urlsplit


class AgentZeroConfigError(ValueError):
    pass


def _env(name: str, fallback: object) -> object:
    value = os.environ.get(name)
    return fallback if value is None else value


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    raise AgentZeroConfigError(f"invalid boolean value: {value!r}")


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise AgentZeroConfigError(f"{name} must be a string")
    return value.strip()


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise AgentZeroConfigError(f"{name} must be a finite number")
    return float(value)


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AgentZeroConfigError(f"{name} must be an integer")
    return value


@dataclass(frozen=True)
class AgentZeroConfig:
    enabled: bool = True
    base_url: str = ""
    allow_remote: bool = False
    api_key: str = ""
    timeout_seconds: float = 60.0
    max_message_chars: int = 20000
    max_response_bytes: int = 1048576

    @classmethod
    def load(cls, mapping: dict | None) -> "AgentZeroConfig":
        source = dict(mapping or {})
        config = cls(
            enabled=_bool(source.get("enabled", True)),
            base_url=_string(
                _env("ZARA_AGENT_ZERO_URL", source.get("base_url", "")),
                "base_url",
            ).rstrip("/"),
            allow_remote=_bool(source.get("allow_remote", False)),
            api_key=_string(
                _env("ZARA_AGENT_ZERO_API_KEY", source.get("api_key", "")),
                "api_key",
            ),
            timeout_seconds=_number(source.get("timeout_seconds", 60.0), "timeout_seconds"),
            max_message_chars=_integer(source.get("max_message_chars", 20000), "max_message_chars"),
            max_response_bytes=_integer(source.get("max_response_bytes", 1048576), "max_response_bytes"),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or not 0.1 <= self.timeout_seconds <= 300
        ):
            raise AgentZeroConfigError("timeout_seconds must be between 0.1 and 300")
        if (
            isinstance(self.max_message_chars, bool)
            or not isinstance(self.max_message_chars, int)
            or not 1 <= self.max_message_chars <= 200000
        ):
            raise AgentZeroConfigError("max_message_chars must be between 1 and 200000")
        if (
            isinstance(self.max_response_bytes, bool)
            or not isinstance(self.max_response_bytes, int)
            or not 1024 <= self.max_response_bytes <= 8388608
        ):
            raise AgentZeroConfigError("max_response_bytes must be between 1024 and 8388608")
        if not isinstance(self.base_url, str) or not isinstance(self.api_key, str):
            raise AgentZeroConfigError("base_url and api_key must be strings")
        if not self.base_url:
            return

        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise AgentZeroConfigError("base_url must be an http(s) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise AgentZeroConfigError(
                "base_url must not contain credentials, query, or fragment"
            )
        if self.allow_remote:
            return

        host = parsed.hostname.lower()
        if host == "localhost":
            return
        try:
            address = ipaddress.ip_address(host)
        except ValueError as error:
            raise AgentZeroConfigError(
                "remote Agent Zero host requires allow_remote=true"
            ) from error
        if not address.is_loopback:
            raise AgentZeroConfigError(
                "remote Agent Zero host requires allow_remote=true"
            )
