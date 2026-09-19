from __future__ import annotations

import math


class MusicError(RuntimeError):
    pass


_STRATEGIES = {
    "familiar",
    "discovery",
    "rediscovery",
    "similar",
    "era",
    "mood",
    "deep-cut",
    "album-flow",
    "sonic-path",
}


class MusicDomain:
    def __init__(
        self,
        backend,
        *,
        max_search_results: int = 50,
        max_recommendations: int = 50,
    ) -> None:
        if type(max_search_results) is not int or not 1 <= max_search_results <= 100:
            raise MusicError("max_search_results must be an integer between 1 and 100")
        if type(max_recommendations) is not int or not 1 <= max_recommendations <= 100:
            raise MusicError("max_recommendations must be an integer between 1 and 100")
        self.backend = backend
        self.max_search_results = max_search_results
        self.max_recommendations = max_recommendations

    @staticmethod
    def _text(value: object, *, name: str, limit: int = 512) -> str:
        if not isinstance(value, str) or not value.strip():
            raise MusicError(f"{name} must be a non-empty string")
        if value != value.strip():
            raise MusicError(f"{name} must not have surrounding whitespace")
        if len(value.encode("utf-8")) > limit:
            raise MusicError(f"{name} exceeds byte limit")
        if any(ord(character) < 0x20 for character in value):
            raise MusicError(f"{name} contains control characters")
        return value

    @staticmethod
    def _optional_player(player_id: object) -> str | None:
        if player_id in (None, ""):
            return None
        return MusicDomain._text(player_id, name="player_id", limit=256)

    @staticmethod
    def _limit(value: object, *, maximum: int, name: str) -> int:
        if type(value) is not int:
            raise MusicError(f"{name} must be an integer")
        if not 1 <= value <= maximum:
            raise MusicError(f"{name} is out of range")
        return value

    @classmethod
    def _track(cls, value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            raise MusicError("track must be an object")
        required = {"media_id", "title", "provider"}
        if not required.issubset(value):
            raise MusicError("track is missing required fields")
        duration = value.get("duration_ms")
        if duration is not None:
            if type(duration) is not int or duration < 0:
                raise MusicError("duration_ms must be a non-negative integer")
        artist = value.get("artist")
        album = value.get("album")
        return {
            "media_id": cls._text(value["media_id"], name="media_id", limit=256),
            "title": cls._text(value["title"], name="title", limit=1024),
            "artist": None
            if artist in (None, "")
            else cls._text(artist, name="artist", limit=512),
            "album": None
            if album in (None, "")
            else cls._text(album, name="album", limit=512),
            "duration_ms": duration,
            "provider": cls._text(value["provider"], name="provider", limit=128),
        }

    @staticmethod
    def _mutation(value: object, *, operation: str) -> dict[str, object]:
        if not isinstance(value, dict):
            raise MusicError(f"{operation} backend result must be an object")
        accepted = value.get("accepted")
        verified = value.get("verified")
        if type(accepted) is not bool or type(verified) is not bool:
            raise MusicError(f"{operation} accepted/verified evidence must be boolean")
        return {
            "status": "verified" if accepted and verified else "verification_failed",
            "accepted": accepted,
            "verified": verified,
        }

    def status(self) -> dict[str, object]:
        value = self.backend.status()
        if not isinstance(value, dict):
            raise MusicError("music backend returned invalid status")
        return dict(value)

    def current(self, player_id: str | None = None) -> dict[str, object] | None:
        player = self._optional_player(player_id)
        value = self.backend.current(player)
        return None if value is None else self._track(value)

    def search(self, query: str, *, limit: int = 25) -> dict[str, object]:
        query = self._text(query, name="query", limit=4096)
        limit = self._limit(limit, maximum=self.max_search_results, name="search limit")
        values = self.backend.search(query, limit)
        if not isinstance(values, list):
            raise MusicError("music backend returned invalid search results")
        return {
            "status": "ok",
            "query": query,
            "results": [self._track(value) for value in values[:limit]],
        }

    def recommend(
        self,
        strategy: str = "familiar",
        *,
        limit: int = 10,
        seed_media_id: str | None = None,
    ) -> dict[str, object]:
        strategy = self._text(strategy, name="strategy", limit=64)
        if strategy not in _STRATEGIES:
            raise MusicError("unknown-strategy")
        limit = self._limit(
            limit,
            maximum=self.max_recommendations,
            name="recommendation limit",
        )
        seed = (
            None
            if seed_media_id in (None, "")
            else self._text(seed_media_id, name="seed_media_id", limit=256)
        )
        value = self.backend.recommend(strategy, limit, seed)
        if not isinstance(value, dict):
            raise MusicError("music backend returned invalid recommendation result")
        results = value.get("results")
        explanation = value.get("explanation", [])
        if not isinstance(results, list) or not isinstance(explanation, list):
            raise MusicError("music backend returned invalid recommendation payload")
        bounded_explanation = []
        for item in explanation[:32]:
            bounded_explanation.append(
                self._text(item, name="recommendation explanation", limit=1024)
            )
        return {
            "status": "ok",
            "strategy": strategy,
            "seed_media_id": seed,
            "results": [self._track(item) for item in results[:limit]],
            "explanation": bounded_explanation,
        }

    def play(self, media_id: str, player_id: str | None = None) -> dict[str, object]:
        media_id = self._text(media_id, name="media_id", limit=256)
        player = self._optional_player(player_id)
        result = self._mutation(
            self.backend.play(media_id, player),
            operation="play",
        )
        return {**result, "media_id": media_id, "player_id": player}

    def pause(self, player_id: str | None = None) -> dict[str, object]:
        player = self._optional_player(player_id)
        result = self._mutation(self.backend.pause(player), operation="pause")
        return {**result, "player_id": player}

    def volume(self, volume: float, player_id: str | None = None) -> dict[str, object]:
        if type(volume) not in {int, float}:
            raise MusicError("volume must be numeric")
        normalized = float(volume)
        if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
            raise MusicError("volume is out of range")
        player = self._optional_player(player_id)
        result = self._mutation(
            self.backend.set_volume(normalized, player),
            operation="volume",
        )
        return {**result, "volume": normalized, "player_id": player}

    def _current_track_required(self, player_id: str | None) -> tuple[str | None, dict[str, object]]:
        player = self._optional_player(player_id)
        track = self.current(player)
        if track is None:
            raise MusicError("current track is unavailable")
        return player, track

    def favorite_current(self, player_id: str | None = None) -> dict[str, object]:
        player, track = self._current_track_required(player_id)
        result = self._mutation(
            self.backend.add_favorite(track["media_id"]),
            operation="favorite-current",
        )
        return {
            **result,
            "player_id": player,
            "media_id": track["media_id"],
            "track": track,
        }

    def playlist_add_current(
        self,
        playlist_id: str,
        player_id: str | None = None,
    ) -> dict[str, object]:
        playlist_id = self._text(playlist_id, name="playlist_id", limit=256)
        player, track = self._current_track_required(player_id)
        result = self._mutation(
            self.backend.add_to_playlist(playlist_id, track["media_id"]),
            operation="playlist-add-current",
        )
        return {
            **result,
            "player_id": player,
            "playlist_id": playlist_id,
            "media_id": track["media_id"],
            "track": track,
        }
