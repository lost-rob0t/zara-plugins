import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_voice.domain import VoicePolicy, VoiceProfile, VoiceService


class CancellableBackend:
    name = "local"
    locality = "local"
    capabilities = frozenset()

    def __init__(self) -> None:
        self.cancelled: list[str] = []

    def synthesize(self, request):
        return {
            "audio": b"RIFFrollback",
            "format": "wav",
            "sample_rate_hz": 24000,
            "duration_seconds": 0.4,
            "request_id": "req-rollback",
        }

    def cancel(self, request_id: str) -> bool:
        self.cancelled.append(request_id)
        return True


class NoopPlayer:
    def play(self, artifact):
        return {"playback_id": "unused"}

    def cancel(self, playback_id):
        return True


class FailingCacheVoiceService(VoiceService):
    def _cache(self, artifact_id: str, audio: bytes) -> None:
        raise OSError("simulated cache write failure")


class CacheFailureRollbackTests(unittest.TestCase):
    def test_failed_cache_write_does_not_publish_artifact_or_request_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            backend = CancellableBackend()
            voice = FailingCacheVoiceService(
                backends={"local": backend},
                player=NoopPlayer(),
                cache_root=Path(temporary),
                policy=VoicePolicy(
                    max_text_chars=64,
                    max_audio_bytes=64,
                    max_duration_seconds=2.0,
                    max_cache_bytes=128,
                ),
            )
            voice.register_profile(
                VoiceProfile(name="local", backend="local", backend_profile="voice-a")
            )

            with self.assertRaisesRegex(OSError, "cache write failure"):
                voice.synthesize("first", profile="local", cache=True)

            self.assertEqual(voice._artifacts, {})
            self.assertEqual(voice._artifact_bytes, 0)
            self.assertNotIn("req-rollback", voice._request_backends)

            artifact = voice.synthesize("retry", profile="local", cache=False)
            self.assertEqual(artifact["request_id"], "req-rollback")
            self.assertTrue(voice.cancel(request_id="req-rollback")["cancelled"])
            self.assertEqual(backend.cancelled, ["req-rollback"])


if __name__ == "__main__":
    unittest.main()
