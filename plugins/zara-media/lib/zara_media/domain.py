from __future__ import annotations


class MediaError(RuntimeError):
    pass


_MEDIA_KEYS = (
    "media_id",
    "kind",
    "title",
    "artist",
    "show",
    "duration_ms",
    "provider",
)


class MediaDomain:
    def __init__(self, backend, *, max_queue_items: int = 100, max_search_results: int = 25) -> None:
        if not 1 <= int(max_queue_items) <= 1000:
            raise MediaError("max_queue_items is out of range")
        if not 1 <= int(max_search_results) <= 100:
            raise MediaError("max_search_results is out of range")
        self.backend = backend
        self.max_queue_items = int(max_queue_items)
        self.max_search_results = int(max_search_results)

    @staticmethod
    def _bounded(value: str, *, name: str, limit: int = 512) -> str:
        if not isinstance(value, str) or not value.strip():
            raise MediaError(f"{name} must be a non-empty string")
        if len(value.encode("utf-8")) > limit:
            raise MediaError(f"{name} exceeds byte limit")
        if any(ord(character) < 0x20 for character in value):
            raise MediaError(f"{name} contains control characters")
        return value

    @classmethod
    def _item(cls, item: object) -> dict[str, object]:
        if not isinstance(item, dict):
            raise MediaError("media item must be an object")
        required = {"media_id", "kind", "title", "duration_ms", "provider"}
        if not required.issubset(item):
            raise MediaError("media item is missing required fields")
        media_id = cls._bounded(item["media_id"], name="media id")
        kind = cls._bounded(item["kind"], name="media kind", limit=64)
        if kind not in {"track", "episode", "video", "stream", "other"}:
            raise MediaError("media kind is not supported")
        title = cls._bounded(item["title"], name="title", limit=1024)
        provider = cls._bounded(item["provider"], name="provider", limit=128)
        duration_ms = item["duration_ms"]
        if duration_ms is not None:
            try:
                duration_ms = int(duration_ms)
            except (TypeError, ValueError) as error:
                raise MediaError("duration_ms is invalid") from error
            if duration_ms < 0 or duration_ms > 7 * 24 * 60 * 60 * 1000:
                raise MediaError("duration_ms is out of range")
        artist = item.get("artist")
        show = item.get("show")
        if artist is not None:
            artist = cls._bounded(artist, name="artist", limit=512)
        if show is not None:
            show = cls._bounded(show, name="show", limit=512)
        return {
            "media_id": media_id,
            "kind": kind,
            "title": title,
            "artist": artist,
            "show": show,
            "duration_ms": duration_ms,
            "provider": provider,
        }

    @classmethod
    def _player(cls, player: object) -> dict[str, object]:
        if not isinstance(player, dict):
            raise MediaError("player state must be an object")
        player_id = cls._bounded(player.get("player_id"), name="player id", limit=256)
        state = str(player.get("state", "unknown"))
        if state not in {"playing", "paused", "stopped", "buffering", "unknown"}:
            state = "unknown"
        volume = player.get("volume")
        if volume is not None:
            try:
                volume = float(volume)
            except (TypeError, ValueError) as error:
                raise MediaError("player volume is invalid") from error
            if not 0.0 <= volume <= 1.0:
                raise MediaError("player volume is out of range")
        position = player.get("position_ms")
        if position is not None:
            try:
                position = int(position)
            except (TypeError, ValueError) as error:
                raise MediaError("player position is invalid") from error
            if position < 0:
                raise MediaError("player position is out of range")
        item = player.get("item")
        return {
            "player_id": player_id,
            "name": str(player.get("name", player_id))[:512],
            "device": str(player.get("device", "unknown"))[:256],
            "state": state,
            "volume": volume,
            "muted": bool(player.get("muted", False)),
            "position_ms": position,
            "item": None if item is None else cls._item(item),
        }

    def players(self) -> list[dict[str, object]]:
        values = self.backend.list_players()
        if not isinstance(values, list):
            raise MediaError("media backend returned invalid player list")
        return [self._player(value) for value in values[:64]]

    def _require_player(self, player_id: str | None) -> str:
        if player_id is None:
            raise MediaError("player_id is required when controlling playback")
        player_id = self._bounded(player_id, name="player id", limit=256)
        if player_id not in {player["player_id"] for player in self.players()}:
            raise MediaError("unknown player")
        return player_id

    def state(self, player_id: str) -> dict[str, object]:
        player_id = self._require_player(player_id)
        return self._player(self.backend.player_state(player_id))

    def context(self) -> dict[str, object]:
        players = self.players()
        active = self.backend.active_player_id()
        active_id = None
        playback = None
        if active is not None:
            active_id = self._bounded(active, name="active player id", limit=256)
            matching = next((player for player in players if player["player_id"] == active_id), None)
            playback = matching
        return {
            "active_player_id": active_id,
            "playback": playback,
            "players": players,
        }

    def select_player(self, player_id: str) -> dict[str, object]:
        player_id = self._require_player(player_id)
        evidence = self.backend.set_active_player(player_id)
        if not isinstance(evidence, dict):
            raise MediaError("media backend returned invalid selection evidence")
        accepted = bool(evidence.get("accepted"))
        after = self.backend.active_player_id()
        verified = accepted and after == player_id
        return {
            "status": "verified" if verified else "verification_failed",
            "accepted": accepted,
            "verified": verified,
            "player_id": player_id,
            "after_active_player_id": after,
            "evidence": evidence,
        }

    def playback(self, player_id: str | None, action: str, *, value=None) -> dict[str, object]:
        player_id = self._require_player(player_id)
        if action not in {"play", "pause", "stop", "seek", "skip_next", "skip_previous", "volume", "mute"}:
            raise MediaError("playback action is not allowlisted")
        normalized_value = value
        if action == "seek":
            try:
                normalized_value = int(value)
            except (TypeError, ValueError) as error:
                raise MediaError("seek value must be milliseconds") from error
            if normalized_value < 0 or normalized_value > 7 * 24 * 60 * 60 * 1000:
                raise MediaError("seek value is out of range")
        elif action == "volume":
            try:
                normalized_value = float(value)
            except (TypeError, ValueError) as error:
                raise MediaError("volume value must be numeric") from error
            if not 0.0 <= normalized_value <= 1.0:
                raise MediaError("volume value is out of range")
        elif action == "mute":
            if type(value) is not bool:
                raise MediaError("mute value must be boolean")
            normalized_value = value
        elif value is not None:
            raise MediaError("playback action does not accept a value")

        before = self.state(player_id)
        evidence = self.backend.playback_action(player_id, action, normalized_value)
        if not isinstance(evidence, dict):
            raise MediaError("media backend returned invalid playback evidence")
        after = self.state(player_id)
        accepted = bool(evidence.get("accepted"))
        if action == "play":
            observed = after["state"] == "playing"
        elif action == "pause":
            observed = after["state"] == "paused"
        elif action == "stop":
            observed = after["state"] == "stopped"
        elif action == "seek":
            observed = after["position_ms"] == normalized_value
        elif action == "volume":
            observed = after["volume"] == normalized_value
        elif action == "mute":
            observed = after["muted"] is normalized_value
        else:
            observed = after != before
        verified = accepted and observed
        return {
            "status": "verified" if verified else "verification_failed",
            "accepted": accepted,
            "verified": verified,
            "player_id": player_id,
            "action": action,
            "before": before,
            "after": after,
            "evidence": evidence,
        }

    def queue(self, player_id: str) -> list[dict[str, object]]:
        player_id = self._require_player(player_id)
        queue = self.backend.queue(player_id)
        if not isinstance(queue, list):
            raise MediaError("media backend returned invalid queue")
        return [self._item(item) for item in queue[: self.max_queue_items]]

    def queue_add(self, player_id: str, item: dict[str, object]) -> dict[str, object]:
        player_id = self._require_player(player_id)
        normalized = self._item(item)
        before = self.queue(player_id)
        if len(before) >= self.max_queue_items:
            raise MediaError("queue item limit reached")
        evidence = self.backend.queue_add(player_id, normalized)
        if not isinstance(evidence, dict):
            raise MediaError("media backend returned invalid queue evidence")
        after = self.queue(player_id)
        accepted = bool(evidence.get("accepted"))
        verified = accepted and len(after) == len(before) + 1 and after[-1] == normalized
        return {
            "status": "verified" if verified else "verification_failed",
            "accepted": accepted,
            "verified": verified,
            "queue": after,
            "evidence": evidence,
        }

    def queue_move(self, player_id: str, source_index: int, destination_index: int) -> dict[str, object]:
        player_id = self._require_player(player_id)
        before = self.queue(player_id)
        try:
            source_index = int(source_index)
            destination_index = int(destination_index)
        except (TypeError, ValueError) as error:
            raise MediaError("queue index is invalid") from error
        if not 0 <= source_index < len(before) or not 0 <= destination_index < len(before):
            raise MediaError("queue index is out of range")
        expected = list(before)
        item = expected.pop(source_index)
        expected.insert(destination_index, item)
        evidence = self.backend.queue_move(player_id, source_index, destination_index)
        if not isinstance(evidence, dict):
            raise MediaError("media backend returned invalid queue evidence")
        after = self.queue(player_id)
        accepted = bool(evidence.get("accepted"))
        verified = accepted and after == expected
        return {
            "status": "verified" if verified else "verification_failed",
            "accepted": accepted,
            "verified": verified,
            "queue": after,
            "evidence": evidence,
        }

    def search(self, query: str, *, limit: int | None = None) -> dict[str, object]:
        query = self._bounded(query, name="catalog query", limit=4096)
        selected_limit = self.max_search_results if limit is None else int(limit)
        if not 1 <= selected_limit <= self.max_search_results:
            raise MediaError("search result limit is out of range")
        values = self.backend.catalog_search(query, selected_limit)
        if not isinstance(values, list):
            raise MediaError("media backend returned invalid catalog results")
        return {"status": "ok", "results": [self._item(item) for item in values[:selected_limit]]}

    def like_this_query(self, item: dict[str, object]) -> dict[str, object]:
        normalized = self._item(item)
        return {
            "kind": normalized["kind"],
            "title": normalized["title"],
            "artist": normalized["artist"],
            "show": normalized["show"],
            "provider": normalized["provider"],
        }
