"""Bounded subprocess bridge to the local-recall CLI."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .paths import MAX_RESPONSE_BYTES, PluginSettings

Runner = Callable[..., subprocess.CompletedProcess[bytes]]


@dataclass(frozen=True, slots=True, repr=False)
class CliResult:
    outcome: str
    text: str
    reason_code: str | None

    def __repr__(self) -> str:
        return f"CliResult(outcome={self.outcome!r}, text=<bounded>, reason={self.reason_code!r})"


def build_command(arguments: list[str]) -> list[str]:
    return ["local-recall", *arguments, "--json"]


def parse_output(stdout: bytes) -> CliResult:
    if len(stdout) > MAX_RESPONSE_BYTES:
        raise RuntimeError("cli-response-too-large")
    try:
        document: Any = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("cli-response-invalid") from exc
    if not isinstance(document, dict):
        raise RuntimeError("cli-response-invalid")
    outcome = document.get("outcome")
    if not isinstance(outcome, str) or not outcome:
        raise RuntimeError("cli-response-invalid")
    reason = document.get("reason_code")
    text = document.get("text")
    return CliResult(
        outcome=outcome,
        text=text if isinstance(text, str) else "",
        reason_code=reason if isinstance(reason, str) else None,
    )


def run_cli(
    arguments: list[str],
    *,
    settings: PluginSettings,
    runner: Runner | None = None,
) -> CliResult:
    resolved_runner = runner or subprocess.run
    command = build_command(arguments)
    try:
        completed = resolved_runner(  # type: ignore[call-arg]
            command,
            capture_output=True,
            timeout=settings.cli_timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("cli-timeout") from exc
    except FileNotFoundError as exc:
        raise RuntimeError("cli-unavailable") from exc
    if completed.returncode not in (0, 2, 3, 4, 5):
        raise RuntimeError("cli-failed")
    return parse_output(completed.stdout)


def ask(question: str, *, settings: PluginSettings, runner: Runner | None = None) -> CliResult:
    if not question.strip():
        raise RuntimeError("empty-query")
    return run_cli(["ask", question], settings=settings, runner=runner)


def search(
    query: str,
    *,
    start: str,
    end: str,
    settings: PluginSettings,
    runner: Runner | None = None,
) -> CliResult:
    if not query.strip() or not start or not end:
        raise RuntimeError("invalid-search-scope")
    return run_cli(
        ["search", query, "--start", start, "--end", end],
        settings=settings,
        runner=runner,
    )


def status(*, settings: PluginSettings, runner: Runner | None = None) -> CliResult:
    return run_cli(["status"], settings=settings, runner=runner)
