import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_voice.domain import VoiceDomain, VoiceError


class FakeBackend:
    def __init__(self, name, locality="local", capabilities=None):
        self.name = name
        self.locality = locality
        self.capabilities = set(capabilities or [])
        self.played = []
        self.cancelled = []

    def profiles(self):
        return [{"profile_id": "voice-1", "name": "Voice One", "languages": ["en"], "styles": ["calm"] if "style" in self.capabilities else [], "emotions": ["happy"] if "emotion" in self.capabilities else []}]

    def synthesize(self, request):
        payload = (request["text"] + "|" + request["profile_id"]).encode("utf-8")
        return {"audio": payload, "format": "wav", "sample_rate": 24000, "duration_seconds": min(30.0, len(payload) / 10.0)}

    def play(self, artifact):
        self.played.append(artifact["artifact_id"])
        return {"accepted": True, "playback_id": "play-1"}

    def cancel(self, playback_id):
        self.cancelled.append(playback_id)
        return {"accepted": True, "playback_id": playback_id}

    def health(self):
        return {"status": "ready", "latency_ms": 12}


class VoiceDomainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.local = FakeBackend("local-tts", capabilities={"style", "emotion"})
        self.remote = FakeBackend("remote-tts", locality="remote")
        self.voice = VoiceDomain({"local-tts": self.local, "remote-tts": self.remote}, Path(self.tmp.name), max_text_bytes=100, max_audio_bytes=1024, max_cache_bytes=2048)

    def tearDown(self):
        self.tmp.cleanup()

    def test_profiles_expose_backend_locality_and_capabilities(self):
        profiles = self.voice.profiles()
        local = next(item for item in profiles if item["backend"] == "local-tts")
        remote = next(item for item in profiles if item["backend"] == "remote-tts")
        self.assertEqual(local["locality"], "local")
        self.assertEqual(remote["locality"], "remote")
        self.assertIn("style", local["capabilities"])

    def test_remote_synthesis_requires_explicit_allow_remote(self):
        with self.assertRaisesRegex(VoiceError, "remote"):
            self.voice.synthesize("hello", backend="remote-tts", profile_id="voice-1")
        result = self.voice.synthesize("hello", backend="remote-tts", profile_id="voice-1", allow_remote=True)
        self.assertEqual(result["backend"], "remote-tts")
        self.assertEqual(result["locality"], "remote")

    def test_style_and_emotion_are_capability_gated(self):
        result = self.voice.synthesize("hello", backend="local-tts", profile_id="voice-1", style="calm", emotion="happy")
        self.assertEqual(result["style"], "calm")
        with self.assertRaisesRegex(VoiceError, "style"):
            self.voice.synthesize("hello", backend="remote-tts", profile_id="voice-1", style="calm", allow_remote=True)

    def test_text_output_and_duration_are_bounded(self):
        with self.assertRaisesRegex(VoiceError, "text"):
            self.voice.synthesize("x" * 101, backend="local-tts", profile_id="voice-1")
        huge = FakeBackend("huge")
        huge.synthesize = lambda request: {"audio": b"x" * 2048, "format": "wav", "sample_rate": 24000, "duration_seconds": 5}
        domain = VoiceDomain({"huge": huge}, Path(self.tmp.name) / "huge", max_audio_bytes=1024)
        with self.assertRaisesRegex(VoiceError, "audio"):
            domain.synthesize("ok", backend="huge", profile_id="voice-1")
        long = FakeBackend("long")
        long.synthesize = lambda request: {"audio": b"x", "format": "wav", "sample_rate": 24000, "duration_seconds": 999}
        domain = VoiceDomain({"long": long}, Path(self.tmp.name) / "long", max_duration_seconds=60)
        with self.assertRaisesRegex(VoiceError, "duration"):
            domain.synthesize("ok", backend="long", profile_id="voice-1")

    def test_artifact_metadata_identifies_backend_profile_and_format(self):
        result = self.voice.synthesize("hello", backend="local-tts", profile_id="voice-1")
        self.assertEqual(result["backend"], "local-tts")
        self.assertEqual(result["profile_id"], "voice-1")
        self.assertEqual(result["format"], "wav")
        self.assertEqual(result["sample_rate"], 24000)
        self.assertTrue(Path(result["path"]).is_file())

    def test_play_and_cancel_preserve_backend_identity_and_ack(self):
        artifact = self.voice.synthesize("hello", backend="local-tts", profile_id="voice-1")
        played = self.voice.play(artifact["artifact_id"])
        self.assertTrue(played["accepted"])
        self.assertEqual(played["backend"], "local-tts")
        cancelled = self.voice.cancel(played["playback_id"])
        self.assertTrue(cancelled["accepted"])
        self.assertEqual(self.local.cancelled, ["play-1"])

    def test_cache_is_bounded_and_writes_only_under_configured_root(self):
        small = VoiceDomain({"local-tts": self.local}, Path(self.tmp.name) / "cache", max_cache_bytes=25, max_audio_bytes=100)
        first = small.synthesize("1234567890", backend="local-tts", profile_id="voice-1")
        second = small.synthesize("abcdefghij", backend="local-tts", profile_id="voice-1")
        paths = list((Path(self.tmp.name) / "cache").glob("*.wav"))
        self.assertLessEqual(sum(path.stat().st_size for path in paths), 25)
        self.assertTrue(Path(second["path"]).is_relative_to(Path(self.tmp.name) / "cache"))
        self.assertFalse(Path(first["path"]).exists())

    def test_health_normalizes_backend_state(self):
        health = self.voice.health()
        self.assertEqual(health["local-tts"]["status"], "ready")
        self.assertEqual(health["remote-tts"]["locality"], "remote")


if __name__ == "__main__":
    unittest.main()
