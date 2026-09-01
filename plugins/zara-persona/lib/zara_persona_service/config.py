"""Configuration loading for zara-persona."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


DEFAULT_MAX_CHARS = 4000
DEFAULT_PROLOG_TIMEOUT_SECONDS = 2.0
DEFAULT_PROLOG_OUTPUT_LIMIT = 16 * 1024


def _expand_path(value: object | None) -> Path | None:
    if value in (None, ""):
        return None
    return Path(os.path.expandvars(os.path.expanduser(str(value)))).resolve()


def _boolean(value: object, name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{name} must be a boolean")


def _integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _number(value: object, name: str, minimum: float, maximum: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    result = float(value)
    if not minimum <= result <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return result


@dataclass(frozen=True)
class PersonaConfig:
    enabled: bool = True
    prompt: str = ""
    prompt_file: Path | None = None
    prolog_enabled: bool = False
    prolog_file: Path | None = None
    swipl_program: str = "swipl"
    prolog_timeout_seconds: float = DEFAULT_PROLOG_TIMEOUT_SECONDS
    prolog_output_limit: int = DEFAULT_PROLOG_OUTPUT_LIMIT
    max_chars: int = DEFAULT_MAX_CHARS

    @classmethod
    def load(
        cls,
        configuration: Mapping[str, Any] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> "PersonaConfig":
        config = dict(configuration or {})
        env = dict(os.environ if environ is None else environ)

        if "prompt_file" not in config and env.get("ZARA_PERSONA_PROMPT_FILE"):
            config["prompt_file"] = env["ZARA_PERSONA_PROMPT_FILE"]
        if "prolog_file" not in config and env.get("ZARA_PERSONA_PROLOG_FILE"):
            config["prolog_file"] = env["ZARA_PERSONA_PROLOG_FILE"]
        if "swipl_program" not in config and env.get("ZARA_PERSONA_SWIPL"):
            config["swipl_program"] = env["ZARA_PERSONA_SWIPL"]
        if "prolog_enabled" not in config and env.get("ZARA_PERSONA_PROLOG_ENABLED"):
            raw = env["ZARA_PERSONA_PROLOG_ENABLED"].strip().lower()
            if raw not in {"0", "1", "false", "true", "no", "yes", "off", "on"}:
                raise ValueError("ZARA_PERSONA_PROLOG_ENABLED must be boolean-like")
            config["prolog_enabled"] = raw in {"1", "true", "yes", "on"}

        prompt = config.get("prompt", "")
        if not isinstance(prompt, str):
            raise ValueError("prompt must be a string")
        swipl_program = config.get("swipl_program", "swipl")
        if not isinstance(swipl_program, str) or not swipl_program.strip():
            raise ValueError("swipl_program must be a non-empty string")

        return cls(
            enabled=_boolean(config.get("enabled", True), "enabled"),
            prompt=prompt,
            prompt_file=_expand_path(config.get("prompt_file")),
            prolog_enabled=_boolean(
                config.get("prolog_enabled", False), "prolog_enabled"
            ),
            prolog_file=_expand_path(config.get("prolog_file")),
            swipl_program=swipl_program,
            prolog_timeout_seconds=_number(
                config.get("prolog_timeout_seconds", DEFAULT_PROLOG_TIMEOUT_SECONDS),
                "prolog_timeout_seconds",
                0.1,
                30.0,
            ),
            prolog_output_limit=_integer(
                config.get("prolog_output_limit", DEFAULT_PROLOG_OUTPUT_LIMIT),
                "prolog_output_limit",
                256,
                1024 * 1024,
            ),
            max_chars=_integer(
                config.get("max_chars", DEFAULT_MAX_CHARS),
                "max_chars",
                128,
                32768,
            ),
        )

    def validate_files(self) -> None:
        if self.prompt_file is not None and not self.prompt_file.is_file():
            raise ValueError(f"prompt_file does not exist: {self.prompt_file}")
        if self.prolog_enabled:
            if self.prolog_file is None:
                raise ValueError("prolog_file is required when prolog_enabled is true")
            if not self.prolog_file.is_file():
                raise ValueError(f"prolog_file does not exist: {self.prolog_file}")
