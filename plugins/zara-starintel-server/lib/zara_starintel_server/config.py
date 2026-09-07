"""Configuration for the Zara StarIntel Server plugin."""

from __future__ import annotations

import ipaddress
import math
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


class StarIntelConfigError(ValueError):
    pass


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    raise StarIntelConfigError(f"invalid boolean value: {value!r}")


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise StarIntelConfigError(f"{name} must be a finite number")
    return float(value)


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StarIntelConfigError(f"{name} must be an integer")
    return value


def _config_directory() -> Path:
    configured = os.environ.get("XDG_CONFIG_HOME")
    root = Path(configured).expanduser() if configured else Path.home() / ".config"
    return root / "zarathushtra" / "plugins" / "zara-starintel-server"


def _read_secret(path: Path, *, required: bool) -> str:
    if not path.exists():
        if required:
            raise StarIntelConfigError(f"secret file does not exist: {path}")
        return ""
    details = path.lstat()
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
        raise StarIntelConfigError(f"secret file must be a regular file: {path}")
    if details.st_mode & 0o077:
        raise StarIntelConfigError(f"secret file must use mode 0600: {path}")
    if details.st_size > 65536:
        raise StarIntelConfigError(f"secret file is too large: {path}")
    return path.read_text(encoding="utf-8").strip()


def _secret(value_name: str, file_name: str, default_name: str) -> str:
    value = os.environ.get(value_name)
    if value is not None:
        return value.strip()
    explicit_path = os.environ.get(file_name)
    if explicit_path is not None:
        text = explicit_path.strip()
        if not text:
            return ""
        return _read_secret(Path(text).expanduser(), required=True)
    return _read_secret(_config_directory() / default_name, required=False)


def _loopback_host(host: str) -> bool:
    lowered = host.lower()
    if lowered == "localhost" or lowered.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(lowered).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class StarIntelConfig:
    enabled: bool = True
    base_url: str = ""
    api_key: str = field(default="", repr=False)
    bootstrap_secret: str = field(default="", repr=False)
    allow_insecure_http: bool = False
    timeout_seconds: float = 30.0
    max_request_bytes: int = 2097152
    max_response_bytes: int = 8388608

    @classmethod
    def load(cls, mapping: dict | None) -> "StarIntelConfig":
        source = dict(mapping or {})
        base_url = os.environ.get(
            "ZARA_STARINTEL_URL",
            str(source.get("base_url", "")),
        )
        config = cls(
            enabled=_bool(source.get("enabled", True)),
            base_url=str(base_url).strip().rstrip("/"),
            api_key=_secret(
                "ZARA_STARINTEL_API_KEY",
                "ZARA_STARINTEL_API_KEY_FILE",
                "api-key",
            ),
            bootstrap_secret=_secret(
                "ZARA_STARINTEL_BOOTSTRAP_SECRET",
                "ZARA_STARINTEL_BOOTSTRAP_SECRET_FILE",
                "bootstrap-secret",
            ),
            allow_insecure_http=_bool(
                source.get("allow_insecure_http", False)
            ),
            timeout_seconds=_number(source.get("timeout_seconds", 30.0), "timeout_seconds"),
            max_request_bytes=_integer(source.get("max_request_bytes", 2097152), "max_request_bytes"),
            max_response_bytes=_integer(source.get("max_response_bytes", 8388608), "max_response_bytes"),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not 0.1 <= self.timeout_seconds <= 600:
            raise StarIntelConfigError(
                "timeout_seconds must be between 0.1 and 600"
            )
        if not 1 <= self.max_request_bytes <= 67108864:
            raise StarIntelConfigError(
                "max_request_bytes must be between 1 and 67108864"
            )
        if not 1024 <= self.max_response_bytes <= 67108864:
            raise StarIntelConfigError(
                "max_response_bytes must be between 1024 and 67108864"
            )
        if not self.base_url:
            return

        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise StarIntelConfigError("base_url must be an http(s) URL")
        if parsed.username or parsed.password:
            raise StarIntelConfigError("base_url must not contain credentials")
        if parsed.query or parsed.fragment:
            raise StarIntelConfigError(
                "base_url must not contain a query or fragment"
            )
        if (
            parsed.scheme == "http"
            and not _loopback_host(parsed.hostname)
            and not self.allow_insecure_http
        ):
            raise StarIntelConfigError(
                "remote HTTP requires allow_insecure_http=true"
            )
