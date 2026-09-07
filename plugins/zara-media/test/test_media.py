import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_media.domain import MediaDomain, MediaError


class FakeMediaBackend:
    def __init__(self):
        self.players = {
            "living-room": {
                "player_id": "living-room",
                "name": "Living Room",
                "device": "speaker",
                "state": "paused",
                "volume": 0.5,
                "muted": False,
                "position_ms": 1000,
                "item": {
                    "media_id": "track-1",
                    "kind": "track",
                    "title": "First",
                    "artist": "Artist",
                    "show": None,
                    "duration_ms": 180000,
                    "provider": "fake",
                },
            },
            "desk": {
                "player_id": "desk",
                "name": "Desk",
                "device": "headphones",
                "state": "playing",
                "volume": 0.25,
                "muted": False,
                "position_ms": 4000,
                "item": None,
            },
        }
        self.active = "desk"
        self.queues = {"living-room": [], "desk": []}
        self.catalog = [
            {"media_id": "track-1", "kind": "track", "title": "First", "artist": "Artist", "show": None, "duration_ms": 180000, "provider": "fake"},
            {"media_id": "episode-1", "kind": "episode", "title": "Episode", "artist": None, "show": "Show", "duration_ms": 3600000, "provider": "fake"},
        ]
        self.accept_mutations = True

    def list_players(self):
        return [dict(player) for player in self.players.values()]

    def player_state(self, player_id):
        return dict(self.players[player_id])

    def playback_action(self, player_id, action, value=None):
        if not self.accept_mutations:
            return {"accepted": False}
        player = self.players[player_id]
        if action == "play":
            player["state"] = "playing"
        elif action == "pause":
            player["state"] = "paused"
        elif action == "stop":
            player["state"] = "stopped"
        elif action == "seek":
            player["position_ms"] = value
        elif action == "volume":
            player["volume"] = value
        elif action == "mute":
            player["muted"] = value
        return {"accepted": True, "action": action, "value": value}

    def set_active_player(self, player_id):
        if not self.accept_mutations:
            return {"accepted": False}
        self.active = player_id
        return {"accepted": True}

    def active_player_id(self):
        return self.active

    def queue(self, player_id):
        return [dict(item) for item in self.queues[player_id]]

    def queue_add(self, player_id, item):
        if not self.accept_mutations:
            return {"accepted": False}
        self.queues[player_id].append(dict(item))
        return {"accepted": True}

    def queue_move(self, player_id, source_index, destination_index):
        if not self.accept_mutations:
            return {"accepted": False}
        item = self.queues[player_id].pop(source_index)
        self.queues[player_id].insert(destination_index, item)
        return {"accepted": True}

    def catalog_search(self, query, limit):
        query = query.lower()
        return [item for item in self.catalog if query in item["title"].lower()][:limit]


class MediaDomainTest(unittest.TestCase):
    def setUp(self):
        self.backend = FakeMediaBackend()
        self.media = MediaDomain(self.backend, max_queue_items=8, max_search_results=4)

    def test_multiple_players_and_active_context_are_normalized(self):
        players = self.media.players()
        self.assertEqual({player["player_id"] for player in players}, {"living-room", "desk"})
        context = self.media.context()
        self.assertEqual(context["active_player_id"], "desk")
        self.assertEqual(context["playback"]["state"], "playing")
        self.assertNotIn("token", repr(context).lower())

    def test_ambiguous_mutation_requires_explicit_player(self):
        with self.assertRaisesRegex(MediaError, "player_id"):
            self.media.playback(None, "pause")
        result = self.media.playback("desk", "pause")
        self.assertTrue(result["accepted"])
        self.assertTrue(result["verified"])
        self.assertEqual(result["after"]["state"], "paused")

    def test_failed_backend_mutation_never_claims_verified_success(self):
        self.backend.accept_mutations = False
        before = self.media.state("desk")
        result = self.media.playback("desk", "pause")
        self.assertFalse(result["accepted"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["status"], "verification_failed")
        self.assertEqual(result["after"], before)

    def test_seek_volume_and_mute_are_bounded_and_verified(self):
        self.assertTrue(self.media.playback("desk", "seek", value=12345)["verified"])
        self.assertTrue(self.media.playback("desk", "volume", value=0.8)["verified"])
        self.assertTrue(self.media.playback("desk", "mute", value=True)["verified"])
        with self.assertRaises(MediaError):
            self.media.playback("desk", "volume", value=1.1)
        with self.assertRaises(MediaError):
            self.media.playback("desk", "seek", value=-1)

    def test_playback_numeric_values_are_typed_before_backend_mutation(self):
        before = self.media.state("desk")
        for value in (True, 12.5, "12", None):
            with self.subTest(action="seek", value=value):
                with self.assertRaises(MediaError):
                    self.media.playback("desk", "seek", value=value)
                self.assertEqual(self.media.state("desk"), before)
        for value in (True, "0.5", None, math.nan, math.inf, -math.inf):
            with self.subTest(action="volume", value=value):
                with self.assertRaises(MediaError):
                    self.media.playback("desk", "volume", value=value)
                self.assertEqual(self.media.state("desk"), before)

    def test_queue_operations_are_bounded_structured_and_verified(self):
        item = self.backend.catalog[0]
        added = self.media.queue_add("desk", item)
        self.assertTrue(added["verified"])
        self.assertEqual(added["queue"][0]["media_id"], "track-1")
        self.media.queue_add("desk", self.backend.catalog[1])
        moved = self.media.queue_move("desk", 1, 0)
        self.assertTrue(moved["verified"])
        self.assertEqual(moved["queue"][0]["media_id"], "episode-1")
        with self.assertRaises(MediaError):
            self.media.queue_move("desk", 99, 0)

    def test_catalog_search_is_provider_neutral_and_bounded(self):
        result = self.media.search("episode")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["results"][0]["kind"], "episode")
        self.assertNotIn("access_token", repr(result))
        with self.assertRaises(MediaError):
            self.media.search("x" * 5000)

    def test_like_this_query_uses_structured_metadata_only(self):
        query = self.media.like_this_query(
            {
                "media_id": "track-1",
                "kind": "track",
                "title": "First",
                "artist": "Artist",
                "show": None,
                "duration_ms": 180000,
                "provider": "fake",
                "access_token": "must-not-leak",
            }
        )
        self.assertEqual(query["kind"], "track")
        self.assertEqual(query["artist"], "Artist")
        self.assertNotIn("token", repr(query).lower())

    def test_unknown_players_actions_and_media_shapes_fail_closed(self):
        with self.assertRaises(MediaError):
            self.media.state("missing")
        with self.assertRaises(MediaError):
            self.media.playback("desk", "shell")
        with self.assertRaises(MediaError):
            self.media.queue_add("desk", {"title": "missing required fields"})


if __name__ == "__main__":
    unittest.main()
