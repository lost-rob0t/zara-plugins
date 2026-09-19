from __future__ import annotations

import json

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .domain import MusicDomain, MusicError


PLUGIN_VERSION = "0.1.0"


class UnavailableMusicBackend:
    reason = "music-backend-not-configured"

    def __getattr__(self, name):
        raise MusicError(self.reason)


class ZaraMusicPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-music",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Prolog-first Zara Music search, playback, recommendations, favorites, and playlists",
    )

    _SYMBOLS = (
        ("music:current", "music.current", "Read the normalized currently playing track."),
        ("music:search", "music.search", "Search the configured Zara Music catalog."),
        ("music:recommend", "music.recommend", "Produce explainable Prolog-governed music recommendations."),
        ("music:play", "music.play", "Play one exact media item."),
        ("music:pause", "music.pause", "Pause the active or selected music player."),
        ("music:volume", "music.volume", "Set normalized music volume."),
        (
            "music:favorite-current",
            "music.favorite.current",
            "Add the currently playing track to favorites.",
        ),
        (
            "music:playlist-add-current",
            "music.playlist.add_current",
            "Add the currently playing track to an existing playlist.",
        ),
    )

    def __init__(self, backend=None) -> None:
        self.backend = backend or UnavailableMusicBackend()
        self.domain = MusicDomain(self.backend)

    def start(self, runtime) -> None:
        registrar = getattr(runtime, "register_symbol", None)
        if not callable(registrar):
            return
        methods = {
            "music.current": self.current,
            "music.search": self.search,
            "music.recommend": self.recommend,
            "music.play": self.play,
            "music.pause": self.pause,
            "music.volume": self.volume,
            "music.favorite.current": self.favorite_current,
            "music.playlist.add_current": self.playlist_add_current,
        }
        for symbol, capability, docs in self._SYMBOLS:
            registrar(
                symbol,
                "command",
                methods[capability],
                docs=docs,
                capabilities=(capability,),
                source="prolog/zara_music_tools.pl",
            )

    def stop(self) -> None:
        return None

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def status(self) -> str:
        if isinstance(self.backend, UnavailableMusicBackend):
            return self._json({"status": "unavailable", "reason": self.backend.reason})
        return self._json(self.domain.status())

    def current(self, player_id: str = "") -> str:
        return self._json(self.domain.current(player_id or None))

    def search(self, query: str, limit: int = 25) -> str:
        return self._json(self.domain.search(query, limit=limit))

    def recommend(
        self,
        strategy: str = "familiar",
        limit: int = 10,
        seed_media_id: str = "",
    ) -> str:
        return self._json(
            self.domain.recommend(
                strategy,
                limit=limit,
                seed_media_id=seed_media_id or None,
            )
        )

    def play(self, media_id: str, player_id: str = "") -> str:
        return self._json(self.domain.play(media_id, player_id or None))

    def pause(self, player_id: str = "") -> str:
        return self._json(self.domain.pause(player_id or None))

    def volume(self, volume: float, player_id: str = "") -> str:
        return self._json(self.domain.volume(volume, player_id or None))

    def favorite_current(self, player_id: str = "") -> str:
        return self._json(self.domain.favorite_current(player_id or None))

    def playlist_add_current(self, playlist_id: str, player_id: str = "") -> str:
        return self._json(
            self.domain.playlist_add_current(playlist_id, player_id or None)
        )

    def tools(self):
        return (
            StructuredTool.from_function(
                func=self.status,
                name="music.status",
                description="Report Zara Music backend availability.",
            ),
            StructuredTool.from_function(
                func=self.current,
                name="music.current",
                description="Read the normalized currently playing track.",
            ),
            StructuredTool.from_function(
                func=self.search,
                name="music.search",
                description="Search Zara Music with a bounded result count.",
            ),
            StructuredTool.from_function(
                func=self.recommend,
                name="music.recommend",
                description="Return explainable Prolog-governed music recommendations.",
            ),
            StructuredTool.from_function(
                func=self.play,
                name="music.play",
                description="Play one exact media item through the Zara Music service.",
            ),
            StructuredTool.from_function(
                func=self.pause,
                name="music.pause",
                description="Pause the active or selected Zara Music player.",
            ),
            StructuredTool.from_function(
                func=self.volume,
                name="music.volume",
                description="Set normalized player volume from 0.0 through 1.0.",
            ),
            StructuredTool.from_function(
                func=self.favorite_current,
                name="music.favorite.current",
                description="Add the currently playing track to favorites and verify the mutation.",
            ),
            StructuredTool.from_function(
                func=self.playlist_add_current,
                name="music.playlist.add_current",
                description="Add the currently playing track to an existing playlist and verify the mutation.",
            ),
        )


def create_plugin():
    return ZaraMusicPlugin()
