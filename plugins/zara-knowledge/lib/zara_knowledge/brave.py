"""Brave Search adapter for Zara knowledge."""

from __future__ import annotations

import json
import math
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Callable

from .core import SourcedResult


class BraveProviderError(RuntimeError):
    def __init__(self, message: str, *, kind: str = "unavailable") -> None:
        super().__init__(message)
        self.kind = kind


class BraveProvider:
    name = "brave"
    local = False
    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(
        self,
        *,
        api_key: str,
        opener: Callable | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise BraveProviderError("Brave API key is not configured", kind="unavailable")
        if api_key != api_key.strip() or any(ord(character) < 32 or ord(character) == 127 for character in api_key):
            raise BraveProviderError("Brave API key must be a clean string", kind="configuration")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or not 0.1 <= timeout_seconds <= 60
        ):
            raise BraveProviderError("Brave timeout must be between 0.1 and 60 seconds", kind="configuration")
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or not 1024 <= max_response_bytes <= 8 * 1024 * 1024
        ):
            raise BraveProviderError("Brave response limit is out of range", kind="configuration")
        self.api_key = api_key
        self._opener = opener or urllib.request.urlopen
        self.timeout_seconds = float(timeout_seconds)
        self.max_response_bytes = max_response_bytes

    @staticmethod
    def _validate_url(value: str) -> str:
        parsed = urllib.parse.urlsplit(str(value))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise BraveProviderError("Brave returned an invalid result URL", kind="malformed_response")
        return urllib.parse.urlunsplit(parsed)

    def search(
        self,
        query: str,
        *,
        count: int = 5,
        language: str = "",
        safe_search: str = "moderate",
        freshness: str = "",
        **_parameters,
    ) -> list[SourcedResult]:
        if not isinstance(query, str) or not query.strip() or len(query) > 2048:
            raise BraveProviderError("query must contain 1 to 2048 characters", kind="configuration")
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 20:
            raise BraveProviderError("count must be between 1 and 20", kind="configuration")
        if safe_search not in {"off", "moderate", "strict"}:
            raise BraveProviderError("safe_search must be off, moderate, or strict", kind="configuration")
        parameters = {"q": query.strip(), "count": str(count), "safesearch": safe_search}
        if language:
            parameters["search_lang"] = str(language)[:16]
        if freshness:
            parameters["freshness"] = str(freshness)[:32]
        url = f"{self.endpoint}?{urllib.parse.urlencode(parameters)}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "zara-knowledge/0.1.0",
                "X-Subscription-Token": self.api_key,
            },
            method="GET",
        )
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                payload = response.read(self.max_response_bytes + 1)
                if len(payload) > self.max_response_bytes:
                    raise BraveProviderError("Brave response exceeded configured size limit", kind="payload_too_large")
        except urllib.error.HTTPError as error:
            if error.code in {429, 402}:
                raise BraveProviderError("Brave quota or rate limit rejected the request", kind="rate_limited") from error
            raise BraveProviderError(f"Brave request failed with HTTP {error.code}", kind="unavailable") from error
        except (urllib.error.URLError, socket.timeout, TimeoutError) as error:
            raise BraveProviderError("Brave request timed out or was unavailable", kind="timeout") from error
        try:
            document = json.loads(payload.decode("utf-8"))
            raw_results = document.get("web", {}).get("results", [])
            if not isinstance(raw_results, list):
                raise TypeError("results is not a list")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, TypeError) as error:
            raise BraveProviderError("Brave returned malformed JSON", kind="malformed_response") from error
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        results: list[SourcedResult] = []
        for raw in raw_results[:count]:
            if not isinstance(raw, dict):
                raise BraveProviderError("Brave returned a malformed result", kind="malformed_response")
            results.append(
                SourcedResult(
                    provider=self.name,
                    url=self._validate_url(str(raw.get("url", ""))),
                    title=str(raw.get("title", ""))[:512],
                    excerpt=str(raw.get("description", ""))[:4096],
                    timestamp=timestamp,
                    local=False,
                )
            )
        return results
