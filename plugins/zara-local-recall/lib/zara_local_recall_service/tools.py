"""LangChain tools exposing Local Recall queries to the Zara agent."""

from __future__ import annotations

from typing import Any

from . import cli, visual
from .paths import PluginSettings


def build_tools(settings: PluginSettings) -> list[Any]:
    from langchain_core.tools import tool

    @tool
    def local_recall_status() -> str:
        """Read the Local Recall daemon status (capture state, privacy mode)."""
        result = cli.status(settings=settings)
        if result.outcome != "success":
            return f"unavailable: {result.reason_code or result.outcome}"
        return result.text or "reachable"

    @tool
    def local_recall_ask(question: str) -> str:
        """Ask Local Recall what you were doing; question must include one time scope (for example 'today', 'yesterday', 'saturday', or 'last 3 hours')."""
        try:
            result = cli.ask(question, settings=settings)
        except RuntimeError as exc:
            return f"unavailable: {exc}"
        if result.outcome != "success":
            return f"query failed: {result.reason_code or result.outcome}"
        return result.text

    @tool
    def local_recall_search(query: str, start: str, end: str) -> str:
        """Search captured activity between two ISO-8601 timestamps; both bounds are required and timezone-aware (for example 2026-08-31T09:00:00+00:00)."""
        try:
            result = cli.search(
                query, start=start, end=end, settings=settings
            )
        except RuntimeError as exc:
            return f"unavailable: {exc}"
        if result.outcome != "success":
            return f"query failed: {result.reason_code or result.outcome}"
        return result.text

    @tool
    def local_recall_explain_screen() -> str:
        """Explain the current desktop context from Local Recall's recent redacted captures."""
        try:
            answer = visual.explain_screen(
                selector=settings.visual_selector,
                maximum_records=settings.visual_maximum_records,
                timeout_seconds=settings.visual_timeout_seconds,
            )
        except RuntimeError as exc:
            return f"unavailable: {exc}"
        if answer.outcome != "explained":
            return f"not explained: {answer.reason_code or answer.outcome}"
        return answer.explanation

    return [
        local_recall_status,
        local_recall_ask,
        local_recall_search,
        local_recall_explain_screen,
    ]
