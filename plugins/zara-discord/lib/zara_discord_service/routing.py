from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Callable, Generic, TypeVar


DISCORD_MESSAGE_LIMIT = 2000
Response = TypeVar("Response")


def split_discord_message(
    text: str,
    *,
    limit: int = DISCORD_MESSAGE_LIMIT,
) -> list[str]:
    if limit <= 0:
        raise ValueError("message limit must be positive")
    chunks: list[str] = []
    remainder = text
    while remainder:
        if len(remainder) <= limit:
            chunks.append(remainder)
            break
        boundary = max(remainder.rfind("\n", 0, limit + 1), remainder.rfind(" ", 0, limit + 1))
        if boundary <= 0:
            boundary = limit
        else:
            boundary += 1
        chunks.append(remainder[:boundary])
        remainder = remainder[boundary:]
    return chunks


class ResponseRouter(Generic[Response]):
    def __init__(self, *, max_buffered: int = 128) -> None:
        if max_buffered <= 0:
            raise ValueError("max_buffered must be positive")
        self._max_buffered = max_buffered
        self._pending: dict[str, Callable[[Response], None]] = {}
        self._buffered: OrderedDict[str, Response] = OrderedDict()
        self._lock = threading.RLock()

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    @property
    def buffered_count(self) -> int:
        with self._lock:
            return len(self._buffered)

    @property
    def buffered_turn_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._buffered)

    def register(self, turn_id: str, callback: Callable[[Response], None]) -> None:
        with self._lock:
            buffered = self._buffered.pop(turn_id, None)
            if buffered is None:
                self._pending[turn_id] = callback
                return
        callback(buffered)

    def deliver(self, turn_id: str, response: Response) -> None:
        with self._lock:
            callback = self._pending.pop(turn_id, None)
            if callback is None:
                self._buffered[turn_id] = response
                self._buffered.move_to_end(turn_id)
                while len(self._buffered) > self._max_buffered:
                    self._buffered.popitem(last=False)
                return
        callback(response)

    def discard(self, turn_id: str) -> None:
        with self._lock:
            self._pending.pop(turn_id, None)
            self._buffered.pop(turn_id, None)
