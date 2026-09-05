from __future__ import annotations

import json

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .domain import MediaDomain, MediaError


PLUGIN_VERSION = "0.1.0"


class UnavailableMediaBackend:
    reason = "media-backend-not-configured"

    def __getattr__(self, name):
        raise MediaError(self.reason)


class ZaraMediaPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-media",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Provider-neutral media playback, queues, player selection, and catalog queries",
    )

    def __init__(self, backend=None) -> None:
        self.backend = backend or UnavailableMediaBackend()
        self.domain = MediaDomain(self.backend)

    def start(self, runtime) -> None:
        return None

    def stop(self) -> None:
        return None

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def status(self) -> str:
        if isinstance(self.backend, UnavailableMediaBackend):
            return self._json({"status": "unavailable", "reason": self.backend.reason})
        return self._json({"status": "ready", "context": self.domain.context()})

    def players(self) -> str:
        return self._json(self.domain.players())

    def playback_state(self, player_id: str) -> str:
        return self._json(self.domain.state(player_id))

    def context(self) -> str:
        return self._json(self.domain.context())

    def select_player(self, player_id: str) -> str:
        return self._json(self.domain.select_player(player_id))

    def playback(self, player_id: str, action: str, value: float | int | bool | None = None) -> str:
        return self._json(self.domain.playback(player_id, action, value=value))

    def queue(self, player_id: str) -> str:
        return self._json(self.domain.queue(player_id))

    def queue_add(
        self,
        player_id: str,
        media_id: str,
        kind: str,
        title: str,
        duration_ms: int,
        provider: str,
        artist: str = "",
        show: str = "",
    ) -> str:
        item = {
            "media_id": media_id,
            "kind": kind,
            "title": title,
            "duration_ms": duration_ms,
            "provider": provider,
            "artist": artist or None,
            "show": show or None,
        }
        return self._json(self.domain.queue_add(player_id, item))

    def queue_move(self, player_id: str, source_index: int, destination_index: int) -> str:
        return self._json(self.domain.queue_move(player_id, source_index, destination_index))

    def search(self, query: str, limit: int = 25) -> str:
        return self._json(self.domain.search(query, limit=limit))

    def like_this(
        self,
        media_id: str,
        kind: str,
        title: str,
        duration_ms: int,
        provider: str,
        artist: str = "",
        show: str = "",
    ) -> str:
        item = {
            "media_id": media_id,
            "kind": kind,
            "title": title,
            "duration_ms": duration_ms,
            "provider": provider,
            "artist": artist or None,
            "show": show or None,
        }
        return self._json(self.domain.like_this_query(item))

    def tools(self):
        return (
            StructuredTool.from_function(func=self.status, name="media.status", description="Report media backend availability and normalized active playback context."),
            StructuredTool.from_function(func=self.players, name="media.players", description="List bounded normalized player/device records."),
            StructuredTool.from_function(func=self.playback_state, name="media.playback.state", description="Read normalized playback state for one explicit player."),
            StructuredTool.from_function(func=self.context, name="media.context", description="Return normalized active media context suitable for zara-context."),
            StructuredTool.from_function(func=self.select_player, name="media.player.select", description="Select an explicit active player and verify observed selection."),
            StructuredTool.from_function(func=self.playback, name="media.playback.control", description="Run an allowlisted playback mutation against an explicit player and verify observed state."),
            StructuredTool.from_function(func=self.queue, name="media.queue", description="Return a bounded normalized queue for one player."),
            StructuredTool.from_function(func=self.queue_add, name="media.queue.add", description="Append one normalized media item and verify the observed queue."),
            StructuredTool.from_function(func=self.queue_move, name="media.queue.move", description="Move one queue item by bounded indices and verify the observed queue."),
            StructuredTool.from_function(func=self.search, name="media.search", description="Search a configured catalog adapter and return bounded provider-neutral media records."),
            StructuredTool.from_function(func=self.like_this, name="media.like_this", description="Build a structured provider-neutral recommendation query from media metadata."),
        )


def create_plugin():
    return ZaraMediaPlugin()
