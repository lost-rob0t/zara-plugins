import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_voice_lab.domain import VoiceLabError, VoiceLabPolicy, VoiceLabService


class FakeBackend:
    name = "fake-local-trainer"
    locality = "local"
    capabilities = frozenset({"clone", "preview", "style"})

    def __init__(self):
        self.calls = []

    def create(self, request):
        self.calls.append(dict(request))
        return {
            "backend_profile": "voice-abc",
            "model": "fake-1",
            "config": {"epochs": 1},
            "artifacts": {"profile.json": b"{}"},
        }

    def preview(self, request):
        return {"audio": b"preview", "format": "wav", "duration_seconds": 0.3}


class RemoteBackend(FakeBackend):
    name = "fake-remote-trainer"
    locality = "remote"


class VoiceLabTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.backend = FakeBackend()
        self.lab = VoiceLabService(
            backends={"fake-local-trainer": self.backend},
            workspace_root=self.root,
            policy=VoiceLabPolicy(max_sample_bytes=32, max_dataset_bytes=64, max_preview_bytes=32, allow_remote=False),
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_clone_validates_and_records_source_model_provenance(self):
        result = self.lab.create_profile(
            name="mara-clone",
            backend="fake-local-trainer",
            samples=[{"name": "a.wav", "audio": b"RIFFsample", "format": "wav", "sample_rate_hz": 24000}],
            mode="clone",
            source_provenance={"source": "operator", "consent": "supplied"},
        )
        self.assertEqual(result["name"], "mara-clone")
        self.assertEqual(result["backend"], "fake-local-trainer")
        self.assertEqual(result["model"], "fake-1")
        self.assertEqual(result["source_provenance"]["consent"], "supplied")
        self.assertEqual(result["locality"], "local")

    def test_remote_backend_is_refused_without_explicit_policy(self):
        remote = RemoteBackend()
        lab = VoiceLabService(
            backends={"remote": remote},
            workspace_root=self.root,
            policy=VoiceLabPolicy(max_sample_bytes=32, max_dataset_bytes=64, max_preview_bytes=32, allow_remote=False),
        )
        with self.assertRaisesRegex(VoiceLabError, "remote"):
            lab.create_profile(
                name="nope",
                backend="remote",
                samples=[{"name": "a.wav", "audio": b"sample", "format": "wav", "sample_rate_hz": 24000}],
                mode="clone",
                source_provenance={"source": "operator"},
            )
        self.assertEqual(remote.calls, [])

    def test_sample_limit_fails_before_backend(self):
        with self.assertRaisesRegex(VoiceLabError, "sample"):
            self.lab.create_profile(
                name="too-big",
                backend="fake-local-trainer",
                samples=[{"name": "a.wav", "audio": b"x" * 33, "format": "wav", "sample_rate_hz": 24000}],
                mode="clone",
                source_provenance={"source": "operator"},
            )
        self.assertEqual(self.backend.calls, [])

    def test_dataset_total_is_bounded(self):
        with self.assertRaisesRegex(VoiceLabError, "dataset"):
            self.lab.create_profile(
                name="too-many",
                backend="fake-local-trainer",
                samples=[
                    {"name": "a.wav", "audio": b"x" * 32, "format": "wav", "sample_rate_hz": 24000},
                    {"name": "b.wav", "audio": b"x" * 32, "format": "wav", "sample_rate_hz": 24000},
                    {"name": "c.wav", "audio": b"x", "format": "wav", "sample_rate_hz": 24000},
                ],
                mode="clone",
                source_provenance={"source": "operator"},
            )

    def test_preview_is_bounded_and_identifies_profile_backend(self):
        profile = self.lab.create_profile(
            name="preview-me",
            backend="fake-local-trainer",
            samples=[{"name": "a.wav", "audio": b"sample", "format": "wav", "sample_rate_hz": 24000}],
            mode="clone",
            source_provenance={"source": "operator"},
        )
        result = self.lab.preview(profile["profile_id"], "hello", style="calm")
        self.assertEqual(result["backend"], "fake-local-trainer")
        self.assertEqual(result["profile_name"], "preview-me")
        self.assertNotIn("audio", result)

    def test_export_profile_contains_no_source_audio_or_model_weights(self):
        profile = self.lab.create_profile(
            name="export-me",
            backend="fake-local-trainer",
            samples=[{"name": "a.wav", "audio": b"sample", "format": "wav", "sample_rate_hz": 24000}],
            mode="clone",
            source_provenance={"source": "operator"},
        )
        exported = self.lab.export_profile(profile["profile_id"])
        self.assertEqual(exported["runtime_schema"], "zara-voice-profile-v1")
        self.assertNotIn("samples", exported)
        self.assertNotIn("artifacts", exported)
        self.assertEqual(exported["backend_profile"], "voice-abc")

    def test_temporary_source_material_is_cleaned_after_create(self):
        self.lab.create_profile(
            name="clean",
            backend="fake-local-trainer",
            samples=[{"name": "a.wav", "audio": b"sample", "format": "wav", "sample_rate_hz": 24000}],
            mode="clone",
            source_provenance={"source": "operator"},
        )
        self.assertEqual(list((self.root / "tmp").glob("*")) if (self.root / "tmp").exists() else [], [])


if __name__ == "__main__":
    unittest.main()
