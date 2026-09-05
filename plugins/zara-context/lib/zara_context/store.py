from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable, Iterable


ALLOWED_CATEGORIES = frozenset({"application", "window", "workspace", "project", "repository", "file", "selection", "clipboard", "command", "media", "call"})
MAX_ITEMS = 128
MAX_VALUE_BYTES = 8 * 1024
MAX_SOURCE_BYTES = 256
MAX_TTL_SECONDS = 3600.0


class ContextError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContextItem:
    category: str
    value: object
    source: str
    observed_at: float
    expires_at: float
    confidence: float

    def as_dict(self, now: float) -> dict[str, object]:
        return {
            "category": self.category,
            "value": self.value,
            "source": self.source,
            "observed_at": self.observed_at,
            "expires_at": self.expires_at,
            "confidence": self.confidence,
            "stale": now >= self.expires_at,
        }


class ContextStore:
    def __init__(self, *, clock: Callable[[], float] = time.time, default_ttl: float = 30.0) -> None:
        if default_ttl <= 0 or default_ttl > MAX_TTL_SECONDS:
            raise ContextError("default context ttl is out of range")
        self._clock = clock
        self._default_ttl = float(default_ttl)
        self._items: dict[str, ContextItem] = {}

    @staticmethod
    def _validate_value(value: object) -> object:
        try:
            encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise ContextError("context value must be JSON serializable") from error
        if len(encoded) > MAX_VALUE_BYTES:
            raise ContextError("context value exceeds byte limit")
        return value

    def update(self, category: str, value: object, *, source: str, confidence: float = 1.0, ttl: float | None = None) -> ContextItem:
        if category not in ALLOWED_CATEGORIES:
            raise ContextError("context category is unsupported")
        if not isinstance(source, str) or not source.strip() or len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ContextError("context source is invalid")
        confidence = float(confidence)
        if confidence < 0.0 or confidence > 1.0:
            raise ContextError("context confidence must be between 0 and 1")
        effective_ttl = self._default_ttl if ttl is None else float(ttl)
        if effective_ttl <= 0 or effective_ttl > MAX_TTL_SECONDS:
            raise ContextError("context ttl is out of range")
        now = self._clock()
        item = ContextItem(
            category=category,
            value=self._validate_value(value),
            source=source,
            observed_at=now,
            expires_at=now + effective_ttl,
            confidence=confidence,
        )
        if category not in self._items and len(self._items) >= MAX_ITEMS:
            raise ContextError("context store item limit reached")
        self._items[category] = item
        return item

    def current(self, categories: Iterable[str] | None = None) -> dict[str, object]:
        now = self._clock()
        requested = set(categories) if categories is not None else set(self._items)
        unknown = requested - ALLOWED_CATEGORIES
        if unknown:
            raise ContextError("context category is unsupported")
        current: list[dict[str, object]] = []
        stale: list[dict[str, object]] = []
        for category in sorted(requested):
            item = self._items.get(category)
            if item is None:
                continue
            rendered = item.as_dict(now)
            (stale if rendered["stale"] else current).append(rendered)
        return {"status": "ok", "items": current, "stale": stale, "now": now}

    def clear_expired(self) -> int:
        now = self._clock()
        expired = [category for category, item in self._items.items() if now >= item.expires_at]
        for category in expired:
            del self._items[category]
        return len(expired)
