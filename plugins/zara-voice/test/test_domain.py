import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_voice.domain import VoiceDomain, VoiceError


class FakeVoiceBackend:
    def __init__(self, *, locality="local", styles=None, emotions=None):
        self.locality = locality
        self.styles = list(styles or [])
        self.emotions = list(emotions or [])
        self.playback = {}
        self.synthesis_calls = []

    def describe(self):
        return {
            "backend": "fake",
            "locality": self.locality,
            "languages": ["en-US"],
            "styles": self.styles,
            "emotions": self.emotions,
            "streaming": True,
        }

    def profiles(self):
        return [
            {"profile_id": "default", "name": "Default", "languages": ["en-US"]},
            {"profile_id": "calm", "name": "Calm", "languages": ["en-US"]},
        ]

    def synthesize(self, request):
        self.synthesis_calls.append(dict(request))
        return {
            "artifact_id": "artifact-1",
            "format": "wav",
            "sample_rate_hz": 24000,
            "duration_ms": 1200,
            "backend": "fake",
            "profile_id": request["profile_id"],
        }

    def play(self, artifact_id):
        self.playback["playback-1"] = "playing"
        return {"accepted": True, "playback_id": "playback-1", "artifact_id": artifact_id}

    def playback_state(self, playback_id):
        state = self.playback.get(playback_id)
        return None if state is None else {"playback_id": playback_id, "state": state}

    def cancel(self, playback_id):
        if playback_id in self.playback:
            self.playback[playback_id] = "cancelled"
            return {"accepted": True, "playback_id": playback_id}
        return {"accepted": False, "playback_id": playback_id}


class VoiceDomainTest(unittest.TestCase):
    def test_local_backend_profile_synthesis_and_verified_playback(self):
        backend = FakeVoiceBackend(styles=["narration"], emotions=["warm"])
        domain = VoiceDomain({"fake": backend})

        profiles = domain.profiles("fake")
        self.assertEqual([profile["profile_id"] for profile in profiles], ["default", "calm"])

        artifact = domain.synthesize(
            "hello",
            backend="fake",
            profile_id="calm",
            language="en-US",
            style="narration",
            emotion="warm",
        )
        self.assertEqual(artifact["status"], "ready")
        self.assertEqual(artifact["backend"], "fake")
        self.assertEqual(artifact["profile_id"], "calm")

        playback = domain.play("artifact-1", backend="fake")
        self.assertEqual(playback["status"], "verified")
        self.assertTrue(playback["verified"])
        self.assertEqual(playback["state"]["state"], "playing")

        cancelled = domain.cancel("playback-1", backend="fake")
        self.assertEqual(cancelled["status"], "verified")
        self.assertEqual(cancelled["state"]["state"], "cancelled")

    def test_remote_backend_requires_explicit_opt_in(self):
        domain = VoiceDomain({"remote": FakeVoiceBackend(locality="remote")})

        with self.assertRaisesRegex(VoiceError, "remote voice backend is not allowed"):
            domain.synthesize("private text", backend="remote", profile_id="default")

        allowed = VoiceDomain(
            {"remote": FakeVoiceBackend(locality="remote")},
            allow_remote=True,
        )
        self.assertEqual(
            allowed.synthesize("explicit", backend="remote", profile_id="default")["status"],
            "ready",
        )

    def test_text_and_output_duration_are_bounded(self):
        backend = FakeVoiceBackend()
        domain = VoiceDomain({"fake": backend}, max_text_bytes=8, max_duration_ms=1000)

        with self.assertRaisesRegex(VoiceError, "text exceeds byte limit"):
            domain.synthesize("123456789", backend="fake", profile_id="default")

        with self.assertRaisesRegex(VoiceError, "duration exceeds configured limit"):
            domain.synthesize("short", backend="fake", profile_id="default")

    def test_style_and_emotion_are_capability_gated(self):
        domain = VoiceDomain({"fake": FakeVoiceBackend()})

        with self.assertRaisesRegex(VoiceError, "style is not supported"):
            domain.synthesize(
                "hello",
                backend="fake",
                profile_id="default",
                style="narration",
            )
        with self.assertRaisesRegex(VoiceError, "emotion is not supported"):
            domain.synthesize(
                "hello",
                backend="fake",
                profile_id="default",
                emotion="warm",
            )

    def test_unknown_profile_fails_before_provider_action(self):
        backend = FakeVoiceBackend()
        domain = VoiceDomain({"fake": backend})

        with self.assertRaisesRegex(VoiceError, "voice profile is unavailable"):
            domain.synthesize("hello", backend="fake", profile_id="missing")
        self.assertEqual(backend.synthesis_calls, [])

    def test_backend_metadata_is_normalized_without_secret_fields(self):
        class LeakyBackend(FakeVoiceBackend):
            def describe(self):
                value = super().describe()
                value["token"] = "secret"
                value["api_key"] = "secret"
                return value

        domain = VoiceDomain({"fake": LeakyBackend()})
        metadata = domain.backends()[0]
        self.assertNotIn("token", metadata)
        self.assertNotIn("api_key", metadata)
        self.assertEqual(metadata["locality"], "local")


if __name__ == "__main__":
    unittest.main()
