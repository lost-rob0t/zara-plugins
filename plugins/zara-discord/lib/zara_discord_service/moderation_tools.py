from __future__ import annotations

from typing import Callable

from langchain_core.tools import StructuredTool

from .moderation import ModerationContext, ModerationContextStore


MAX_REASON_LENGTH = 500
MAX_TIMEOUT_SECONDS = 28 * 24 * 60 * 60


def _reason(value: str) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > MAX_REASON_LENGTH:
        raise ValueError(f"moderation reason must not exceed {MAX_REASON_LENGTH} characters")
    return text


def _timeout(value: int) -> int:
    seconds = int(value)
    if not 1 <= seconds <= MAX_TIMEOUT_SECONDS:
        raise ValueError(
            f"timeout_seconds must be between 1 and {MAX_TIMEOUT_SECONDS}"
        )
    return seconds


def build_moderation_tools(
    contexts: ModerationContextStore,
    executor: Callable[[str, ModerationContext, str, int | None], str],
):
    def inspect(context_token: str) -> str:
        """Inspect the current Discord moderation target bound to an expiring context token."""
        return executor("inspect", contexts.resolve(context_token), "", None)

    def delete(context_token: str, reason: str = "") -> str:
        """Delete only the Discord message bound to this one-time moderation context token."""
        return executor("delete", contexts.consume(context_token), _reason(reason), None)

    def warn(context_token: str, reason: str) -> str:
        """Reply with a warning only to the author/message bound to this one-time context token."""
        return executor("warn", contexts.consume(context_token), _reason(reason), None)

    def timeout(context_token: str, timeout_seconds: int, reason: str = "") -> str:
        """Timeout only the Discord author bound to this one-time context token."""
        seconds = _timeout(timeout_seconds)
        return executor(
            "timeout",
            contexts.consume(context_token),
            _reason(reason),
            seconds,
        )

    def kick(context_token: str, reason: str = "") -> str:
        """Kick only the Discord author bound to this one-time moderation context token."""
        return executor("kick", contexts.consume(context_token), _reason(reason), None)

    def ban(context_token: str, reason: str = "") -> str:
        """Ban only the Discord author bound to this one-time moderation context token."""
        return executor("ban", contexts.consume(context_token), _reason(reason), None)

    definitions = (
        ("discord_moderation_inspect", inspect),
        ("discord_moderation_delete", delete),
        ("discord_moderation_warn", warn),
        ("discord_moderation_timeout", timeout),
        ("discord_moderation_kick", kick),
        ("discord_moderation_ban", ban),
    )
    return tuple(
        StructuredTool.from_function(
            function,
            name=name,
            description=(function.__doc__ or name).strip(),
        )
        for name, function in definitions
    )
