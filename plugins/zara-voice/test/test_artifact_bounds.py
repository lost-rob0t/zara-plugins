import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_voice.domain import VoiceError, VoicePolicy, VoiceProfile, VoiceService


class ArtifactBackend:
    locality = "local"
    capabilities = frozenset()

    def __init__(self, audio_bytes: int = 8):
        self.audio_bytes = audio_bytes

    def synthesize(self, request):
        return {
            "audio": b"x" * self.audio_bytes,
            "format": "wav",
            "sample_rate_hz": 24000,
            "duration_seconds": 0.4,
            "request_id": None,
        }


class ArtifactPlayer:
    def play(self, artifact):
        return {"playback_id": "play-1", "started": True}

    def cancel(self, playback_id):
        return True


class ArtifactRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def _voice(self, *, audio_bytes: int, max_cache_bytes: int) -> VoiceService:
        backend = ArtifactBackend(audio_bytes=audio_bytes)
        voice = VoiceService(
            backends={"local": backend},
            player=ArtifactPlayer(),
            cache_root=self.root,
            policy=VoicePolicy(
                max_text_chars=64,
                max_audio_bytes=64,
                max_duration_seconds=2.0,
                max_cache_bytes=max_cache_bytes,
            ),
        )
        voice.register_profile(
            VoiceProfile(name="local", backend="local", backend_profile="local")
        )
        return voice

    def test_in_memory_artifact_count_is_bounded_even_without_disk_cache(self):
        voice = self._voice(audio_bytes=8, max_cache_bytes=128)
        artifact_ids = []

        for index in range(40):
            artifact = voice.synthesize(f"utterance {index}", profile="local", cache=False)
            artifact_ids.append(artifact["artifact_id"])

        self.assertLessEqual(len(voice._artifacts), 32)
        with self.assertRaisesRegex(VoiceError, "artifact not found"):
            voice.play(artifact_ids[0])
        self.assertEqual(voice.play(artifact_ids[-1])["playback_id"], "play-1")

    def test_in_memory_artifact_bytes_are_bounded_by_existing_policy_budget(self):
        voice = self._voice(audio_bytes=60, max_cache_bytes=100)
        first = voice.synthesize("first", profile="local", cache=False)
        second = voice.synthesize("second", profile="local", cache=False)

        self.assertNotIn(first["artifact_id"], voice._artifacts)
        self.assertIn(second["artifact_id"], voice._artifacts)
        retained_bytes = sum(len(item["audio"]) for item in voice._artifacts.values())
        self.assertLessEqual(retained_bytes, 100)


if __name__ == "__main__":
    unittest.main()
