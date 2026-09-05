from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import secrets
import threading
import time
from typing import Callable


DEFAULT_CONTEXT_TTL_SECONDS = 120.0
DEFAULT_MAX_CONTEXTS = 256


@dataclass(frozen=True)
class ModerationContext:
    guild_id: int
    channel_id: int
    message_id: int
    target_id: int
    expires_at: float


class ModerationContextStore:
    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_CONTEXT_TTL_SECONDS,
        max_contexts: int = DEFAULT_MAX_CONTEXTS,
        clock: Callable[[], float] = time.monotonic,
        token_factory: Callable[[int], str] = secrets.token_urlsafe,
    ) -> None:
        self.ttl_seconds = float(ttl_seconds)
        self.max_contexts = int(max_contexts)
        if self.ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be greater than zero")
        if self.max_contexts <= 0:
            raise ValueError("max_contexts must be greater than zero")
        self._clock = clock
        self._token_factory = token_factory
        self._contexts: OrderedDict[str, ModerationContext] = OrderedDict()
        self._lock = threading.RLock()

    def issue(
        self,
        *,
        guild_id: int,
        channel_id: int,
        message_id: int,
        target_id: int,
    ) -> str:
        values = {
            "guild_id": guild_id,
            "channel_id": channel_id,
            "message_id": message_id,
            "target_id": target_id,
        }
        normalized = {}
        for name, value in values.items():
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer Discord ID")
            normalized[name] = value

        now = self._clock()
        context = ModerationContext(
            **normalized,
            expires_at=now + self.ttl_seconds,
        )
        with self._lock:
            self._purge_expired(now)
            token = self._new_token()
            while token in self._contexts:
                token = self._new_token()
            self._contexts[token] = context
            while len(self._contexts) > self.max_contexts:
                self._contexts.popitem(last=False)
            return token

    def resolve(self, token: str) -> ModerationContext:
        with self._lock:
            return self._resolve_locked(token, consume=False)

    def consume(self, token: str) -> ModerationContext:
        with self._lock:
            return self._resolve_locked(token, consume=True)

    def _new_token(self) -> str:
        token = str(self._token_factory(32)).strip()
        if len(token) < 32:
            raise ValueError("moderation token source returned an invalid token")
        return token

    def _resolve_locked(self, token: str, *, consume: bool) -> ModerationContext:
        value = str(token or "").strip()
        now = self._clock()
        self._purge_expired(now)
        context = self._contexts.get(value)
        if context is None:
            raise ValueError("moderation context token is expired or unknown")
        if consume:
            del self._contexts[value]
        return context

    def _purge_expired(self, now: float) -> None:
        expired = [
            token
            for token, context in self._contexts.items()
            if context.expires_at <= now
        ]
        for token in expired:
            del self._contexts[token]
