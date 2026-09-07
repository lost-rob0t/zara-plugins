"""Owner-only Local Recall runtime paths and configuration."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path


MAX_RESPONSE_BYTES = 1_310_720
MAX_TOKEN_BYTES = 32
DEFAULT_CLI_TIMEOUT_SECONDS = 15.0
DEFAULT_VISUAL_TIMEOUT_SECONDS = 8.0


@dataclass(frozen=True, slots=True, repr=False)
class RuntimePaths:
    """Validated owner-only daemon IPC endpoints."""

    socket_path: Path
    token_path: Path

    @classmethod
    def from_environment(
        cls,
        *,
        environ: dict[str, str] | None = None,
        uid: int | None = None,
    ) -> RuntimePaths:
        resolved_environ = os.environ if environ is None else environ
        runtime = resolved_environ.get("XDG_RUNTIME_DIR", "")
        if not runtime:
            raise RuntimeError("xdg-runtime-unavailable")
        service_dir = Path(runtime) / "local-recall"
        return cls(
            socket_path=service_dir / "control.sock",
            token_path=service_dir / "session.token",
        )

    def validate(self) -> None:
        for path in (self.socket_path, self.token_path):
            try:
                metadata = path.lstat()
            except OSError as exc:
                raise RuntimeError("runtime-endpoint-unavailable") from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise RuntimeError("runtime-endpoint-symlink")
        if not stat.S_ISSOCK(self.socket_path.lstat().st_mode):
            raise RuntimeError("runtime-endpoint-type")

    def __repr__(self) -> str:
        return "RuntimePaths(paths=<private>)"


@dataclass(frozen=True, slots=True, repr=False)
class PluginSettings:
    """Plugin-owned settings from [plugins.zara-local-recall]."""

    enabled: bool = True
    visual_selector: str = "recent"
    visual_maximum_records: int = 3
    visual_timeout_seconds: float = DEFAULT_VISUAL_TIMEOUT_SECONDS
    cli_timeout_seconds: float = DEFAULT_CLI_TIMEOUT_SECONDS

    @classmethod
    def from_configuration(cls, configuration: dict[str, object]) -> PluginSettings:
        enabled = configuration.get("enabled", True)
        selector = configuration.get("visual_selector", "recent")
        maximum_records = configuration.get("visual_maximum_records", 3)
        visual_timeout = configuration.get("visual_timeout_seconds", DEFAULT_VISUAL_TIMEOUT_SECONDS)
        cli_timeout = configuration.get("cli_timeout_seconds", DEFAULT_CLI_TIMEOUT_SECONDS)
        return cls(
            enabled=enabled if isinstance(enabled, bool) else True,
            visual_selector=(
                selector
                if isinstance(selector, str) and selector in {"current", "recent"}
                else "recent"
            ),
            visual_maximum_records=(
                maximum_records
                if isinstance(maximum_records, int)
                and not isinstance(maximum_records, bool)
                and 1 <= maximum_records <= 8
                else 3
            ),
            visual_timeout_seconds=(
                visual_timeout
                if not isinstance(visual_timeout, bool)
                and isinstance(visual_timeout, (int, float))
                and 0 < float(visual_timeout) <= 30
                else DEFAULT_VISUAL_TIMEOUT_SECONDS
            ),
            cli_timeout_seconds=(
                cli_timeout
                if not isinstance(cli_timeout, bool)
                and isinstance(cli_timeout, (int, float))
                and 0 < float(cli_timeout) <= 60
                else DEFAULT_CLI_TIMEOUT_SECONDS
            ),
        )

    def __repr__(self) -> str:
        return "PluginSettings(settings=redacted)"
