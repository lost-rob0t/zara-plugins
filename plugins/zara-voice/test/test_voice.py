import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_voice.domain import VoiceError, VoicePolicy, VoiceProfile, VoiceService
from zara_voice.plugin import ZaraVoicePlugin


class FakeBackend:
    name = "fake-local"
    locality = "local"
    capabilities = frozenset({"language", "style"})

    def __init__(self):
        self.calls = []
        self.cancelled = []

    def synthesize(self, request):
        self.calls.append(dict(request))
        return {
            "audio": b"RIFFfake",
            "format": "wav",
            "sample_rate_hz": 24000,
            "duration_seconds": 0.4,
            "request_id": "req-1",
        }

    def cancel(self, request_id):
        self.cancelled.append(request_id)
        return True


class NonCancellableBackend:
    name = "non-cancellable"
    locality = "local"
    capabilities = frozenset()

    def synthesize(self, request):
        return {
            "audio": b"RIFFfake",
            "format": "wav",
            "sample_rate_hz": 24000,
            "duration_seconds": 0.4,
            "request_id": "completed-1",
        }


class FakeRemoteBackend(FakeBackend):
    name = "fake-remote"
    locality = "remote"


class FakePlayer:
    def __init__(self):
        self.played = []
        self.cancelled = []
        self.closed = False

    def play(self, artifact):
        self.played.append(dict(artifact))
        return {"playback_id": "play-1", "started": True}

    def cancel(self, playback_id):
        self.cancelled.append(playback_id)
        return True

    def close(self):
        self.closed = True


class FailingClosePlayer(FakePlayer):
    def close(self):
        self.closed = True
        raise VoiceError("player cleanup incomplete")


class VoiceServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.backend = FakeBackend()
        self.player = FakePlayer()
        self.voice = VoiceService(
            backends={"fake-local": self.backend},
            player=self.player,
            cache_root=self.root,
            policy=VoicePolicy(max_text_chars=64, max_audio_bytes=64, max_duration_seconds=2.0, max_cache_bytes=128),
        )
        self.voice.register_profile(VoiceProfile(name="mara", backend="fake-local", backend_profile="voice-a", language="en"))

    def tearDown(self):
        self.temporary.cleanup()

    def test_synthesis_returns_backend_profile_and_normalized_audio_metadata(self):
        result = self.voice.synthesize("hello", profile="mara", style="calm")
        self.assertEqual(result["backend"], "fake-local")
        self.assertEqual(result["profile"], "mara")
        self.assertEqual(result["format"], "wav")
        self.assertEqual(result["sample_rate_hz"], 24000)
        self.assertEqual(result["duration_seconds"], 0.4)
        self.assertNotIn("audio", result)
        self.assertEqual(self.backend.calls[0]["style"], "calm")

    def test_unsupported_emotion_is_rejected_before_backend_call(self):
        with self.assertRaisesRegex(VoiceError, "emotion"):
            self.voice.synthesize("hello", profile="mara", emotion="angry")
        self.assertEqual(self.backend.calls, [])

    def test_text_limit_is_enforced_before_backend_call(self):
        with self.assertRaisesRegex(VoiceError, "text"):
            self.voice.synthesize("x" * 65, profile="mara")
        self.assertEqual(self.backend.calls, [])

    def test_remote_backend_requires_explicit_remote_permission(self):
        remote = FakeRemoteBackend()
        voice = VoiceService(
            backends={"fake-remote": remote},
            player=self.player,
            cache_root=self.root,
            policy=VoicePolicy(max_text_chars=64, max_audio_bytes=64, max_duration_seconds=2.0, max_cache_bytes=128, allow_remote=False),
        )
        voice.register_profile(VoiceProfile(name="remote", backend="fake-remote", backend_profile="r1"))
        with self.assertRaisesRegex(VoiceError, "remote"):
            voice.synthesize("secret text", profile="remote")
        self.assertEqual(remote.calls, [])

    def test_backend_output_limits_fail_closed_and_do_not_cache(self):
        class HugeBackend(FakeBackend):
            def synthesize(self, request):
                return {"audio": b"x" * 65, "format": "wav", "sample_rate_hz": 24000, "duration_seconds": 0.4, "request_id": "huge"}

        voice = VoiceService(
            backends={"huge": HugeBackend()},
            player=self.player,
            cache_root=self.root,
            policy=VoicePolicy(max_text_chars=64, max_audio_bytes=64, max_duration_seconds=2.0, max_cache_bytes=128),
        )
        voice.register_profile(VoiceProfile(name="huge", backend="huge", backend_profile="v"))
        with self.assertRaisesRegex(VoiceError, "audio"):
            voice.synthesize("hello", profile="huge")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_play_and_cancel_use_explicit_ids(self):
        artifact = self.voice.synthesize("hello", profile="mara")
        playback = self.voice.play(artifact["artifact_id"])
        self.assertEqual(playback["playback_id"], "play-1")
        self.assertEqual(self.player.played[0]["audio"], b"RIFFfake")
        result = self.voice.cancel(playback_id="play-1")
        self.assertTrue(result["cancelled"])
        self.assertEqual(self.player.cancelled, ["play-1"])

    def test_cancel_synthesis_delegates_to_backend_request_id(self):
        artifact = self.voice.synthesize("hello", profile="mara")
        result = self.voice.cancel(request_id=artifact["request_id"])
        self.assertTrue(result["cancelled"])
        self.assertEqual(self.backend.cancelled, ["req-1"])
        self.assertNotIn("req-1", self.voice._request_backends)

    def test_completed_non_cancellable_synthesis_does_not_retain_request_state(self):
        backend = NonCancellableBackend()
        voice = VoiceService(
            backends={"non-cancellable": backend},
            player=self.player,
            cache_root=self.root,
            policy=VoicePolicy(max_text_chars=64, max_audio_bytes=64, max_duration_seconds=2.0, max_cache_bytes=128),
        )
        voice.register_profile(VoiceProfile(name="local", backend="non-cancellable", backend_profile="voice-a"))

        artifact = voice.synthesize("hello", profile="local", cache=False)

        self.assertEqual(artifact["request_id"], "completed-1")
        self.assertNotIn("completed-1", voice._request_backends)
        self.assertEqual(
            voice.cancel(request_id="completed-1"),
            {"kind": "synthesis", "id": "completed-1", "cancelled": False},
        )

    def test_cache_eviction_is_bounded(self):
        for index in range(20):
            self.voice.synthesize(f"hello {index}", profile="mara", cache=True)
        total = sum(path.stat().st_size for path in self.root.glob("*.audio"))
        self.assertLessEqual(total, 128)

    def test_plugin_stop_closes_injected_player(self):
        player = FakePlayer()
        plugin = ZaraVoicePlugin(player=player, cache_root=self.root)

        plugin.stop()

        self.assertTrue(player.closed)

    def test_plugin_stop_surfaces_incomplete_player_cleanup(self):
        player = FailingClosePlayer()
        plugin = ZaraVoicePlugin(player=player, cache_root=self.root)

        with self.assertRaisesRegex(VoiceError, "cleanup incomplete"):
            plugin.stop()

        self.assertTrue(player.closed)


if __name__ == "__main__":
    unittest.main()
