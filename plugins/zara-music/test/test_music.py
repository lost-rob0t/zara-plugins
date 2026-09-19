import json
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_music.domain import MusicDomain, MusicError
from zara_music.plugin import ZaraMusicPlugin


TRACK = {
    "media_id": "track-1",
    "title": "First",
    "artist": "Artist",
    "album": "Album",
    "duration_ms": 180000,
    "provider": "fake",
}


class FakeBackend:
    def __init__(self):
        self.current_track = dict(TRACK)
        self.volume_value = 0.5
        self.paused = False
        self.favorites = set()
        self.playlists = {"roadtrip": []}
        self.played = []
        self.search_calls = []
        self.recommend_calls = []

    def status(self):
        return {"status": "ready", "backend": "fake"}

    def current(self, player_id=None):
        return None if self.current_track is None else dict(self.current_track)

    def search(self, query, limit):
        self.search_calls.append((query, limit))
        return [dict(TRACK)]

    def recommend(self, strategy, limit, seed_media_id=None):
        self.recommend_calls.append((strategy, limit, seed_media_id))
        return {
            "strategy": strategy,
            "results": [dict(TRACK)],
            "explanation": ["seeded-by-listening-history"],
        }

    def play(self, media_id, player_id=None):
        self.played.append((media_id, player_id))
        self.paused = False
        return {"accepted": True, "verified": True, "media_id": media_id}

    def pause(self, player_id=None):
        self.paused = True
        return {"accepted": True, "verified": True}

    def set_volume(self, volume, player_id=None):
        self.volume_value = volume
        return {"accepted": True, "verified": True, "volume": volume}

    def add_favorite(self, media_id):
        self.favorites.add(media_id)
        return {"accepted": True, "verified": media_id in self.favorites}

    def add_to_playlist(self, playlist_id, media_id):
        self.playlists.setdefault(playlist_id, []).append(media_id)
        return {
            "accepted": True,
            "verified": media_id in self.playlists[playlist_id],
            "playlist_id": playlist_id,
        }


class FakeRuntime:
    def __init__(self):
        self.registrations = []

    def register_symbol(self, symbol, kind, value, **kwargs):
        self.registrations.append((symbol, kind, value, kwargs))
        return len(self.registrations)


class MusicDomainTest(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.music = MusicDomain(self.backend)

    def test_required_music_surface_is_exposed(self):
        plugin = ZaraMusicPlugin(self.backend)
        names = {tool.name for tool in plugin.tools()}
        self.assertTrue({
            "music.status",
            "music.current",
            "music.search",
            "music.recommend",
            "music.play",
            "music.pause",
            "music.volume",
            "music.favorite.current",
            "music.playlist.add_current",
        }.issubset(names))

    def test_search_and_recommend_are_bounded(self):
        result = self.music.search("first", limit=5)
        self.assertEqual(result["results"][0]["media_id"], "track-1")
        recommendation = self.music.recommend("discovery", limit=3)
        self.assertEqual(recommendation["strategy"], "discovery")
        self.assertEqual(recommendation["results"][0]["media_id"], "track-1")
        with self.assertRaises(MusicError):
            self.music.search("x" * 5000)
        with self.assertRaises(MusicError):
            self.music.recommend("unknown-strategy")

    def test_play_pause_and_volume_are_verified_mutations(self):
        self.assertTrue(self.music.play("track-1")["verified"])
        self.assertTrue(self.music.pause()["verified"])
        self.assertTrue(self.music.volume(0.75)["verified"])
        with self.assertRaises(MusicError):
            self.music.volume(1.01)
        with self.assertRaises(MusicError):
            self.music.volume(True)

    def test_current_song_can_be_favorited_and_added_to_playlist(self):
        favorite = self.music.favorite_current()
        self.assertTrue(favorite["verified"])
        self.assertEqual(favorite["media_id"], "track-1")
        playlist = self.music.playlist_add_current("roadtrip")
        self.assertTrue(playlist["verified"])
        self.assertEqual(playlist["media_id"], "track-1")
        self.assertEqual(self.backend.playlists["roadtrip"], ["track-1"])

    def test_current_song_mutations_fail_closed_when_nothing_is_playing(self):
        self.backend.current_track = None
        with self.assertRaisesRegex(MusicError, "current track"):
            self.music.favorite_current()
        with self.assertRaisesRegex(MusicError, "current track"):
            self.music.playlist_add_current("roadtrip")

    def test_plugin_registers_canonical_command_symbols_for_prolog_runtime(self):
        plugin = ZaraMusicPlugin(self.backend)
        runtime = FakeRuntime()
        plugin.start(runtime)
        registered = {
            (symbol, kind, kwargs["capabilities"])
            for symbol, kind, _, kwargs in runtime.registrations
        }
        self.assertIn(("music:search", "command", ("music.search",)), registered)
        self.assertIn(("music:recommend", "command", ("music.recommend",)), registered)
        self.assertIn(("music:play", "command", ("music.play",)), registered)
        self.assertIn(("music:pause", "command", ("music.pause",)), registered)
        self.assertIn(("music:volume", "command", ("music.volume",)), registered)
        self.assertIn(
            ("music:favorite-current", "command", ("music.favorite.current",)),
            registered,
        )
        self.assertIn(
            (
                "music:playlist-add-current",
                "command",
                ("music.playlist.add_current",),
            ),
            registered,
        )

    def test_portable_prolog_contract_matches_runtime_symbols(self):
        source = (ROOT / "prolog" / "zara_music_tools.pl").read_text(encoding="utf-8")
        facts = {
            (symbol, capability, effect)
            for symbol, capability, effect in re.findall(
                r"music_tool\('[^']+',\s*'([^']+)',\s*'([^']+)',\s*(read|write)\)\.",
                source,
            )
        }
        self.assertIn(("music:search", "music.search", "read"), facts)
        self.assertIn(("music:recommend", "music.recommend", "read"), facts)
        self.assertIn(("music:play", "music.play", "write"), facts)
        self.assertIn(("music:pause", "music.pause", "write"), facts)
        self.assertIn(("music:volume", "music.volume", "write"), facts)
        self.assertIn(
            ("music:favorite-current", "music.favorite.current", "write"),
            facts,
        )
        self.assertIn(
            (
                "music:playlist-add-current",
                "music.playlist.add_current",
                "write",
            ),
            facts,
        )

    def test_backend_boolean_evidence_cannot_be_truthy_strings(self):
        class BadBackend(FakeBackend):
            def pause(self, player_id=None):
                return {"accepted": "true", "verified": "true"}

        with self.assertRaisesRegex(MusicError, "boolean"):
            MusicDomain(BadBackend()).pause()


if __name__ == "__main__":
    unittest.main()
