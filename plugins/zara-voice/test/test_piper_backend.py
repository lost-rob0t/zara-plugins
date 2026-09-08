import io
import sys
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_voice.domain import VoiceError
from zara_voice.piper import PiperBackend


def wav_bytes(*, frames=240, sample_rate=24000):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\0\0" * frames)
    return buffer.getvalue()


class FakeVoice:
    def __init__(self, audio):
        self.audio = audio
        self.calls = []

    def synthesize_wav(self, text, wav_file):
        self.calls.append(text)
        with wave.open(io.BytesIO(self.audio), "rb") as source:
            wav_file.setnchannels(source.getnchannels())
            wav_file.setsampwidth(source.getsampwidth())
            wav_file.setframerate(source.getframerate())
            wav_file.writeframes(source.readframes(source.getnframes()))


class PiperBackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.model = root / "voice.onnx"
        self.config = root / "voice.onnx.json"
        self.model.write_bytes(b"model")
        self.config.write_text("{}", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def test_loads_explicit_paths_lazily_on_cpu_and_synthesizes_wav(self):
        calls = []
        voice = FakeVoice(wav_bytes(frames=240, sample_rate=24000))

        def load(model_path, *, config_path, use_cuda):
            calls.append((model_path, config_path, use_cuda))
            return voice

        backend = PiperBackend(
            model_path=self.model,
            config_path=self.config,
            loader=load,
            max_audio_bytes=4096,
        )
        self.assertEqual(calls, [])

        result = backend.synthesize({"text": "hello", "profile": "voice-a"})

        self.assertEqual(calls, [(self.model, self.config, False)])
        self.assertEqual(voice.calls, ["hello"])
        self.assertEqual(result["format"], "wav")
        self.assertEqual(result["sample_rate_hz"], 24000)
        self.assertAlmostEqual(result["duration_seconds"], 0.01)
        self.assertTrue(result["audio"].startswith(b"RIFF"))
        self.assertRegex(result["request_id"], r"^[0-9a-f]{32}$")
        self.assertEqual(backend.locality, "local")

    def test_missing_model_or_config_fails_without_disclosing_paths(self):
        missing_model = self.model.with_name("private-secret-model.onnx")
        with self.assertRaises(VoiceError) as caught:
            PiperBackend(model_path=missing_model, config_path=self.config, loader=lambda *a, **k: None)
        self.assertNotIn(str(missing_model), str(caught.exception))

        missing_config = self.config.with_name("private-secret-config.json")
        with self.assertRaises(VoiceError) as caught:
            PiperBackend(model_path=self.model, config_path=missing_config, loader=lambda *a, **k: None)
        self.assertNotIn(str(missing_config), str(caught.exception))

    def test_loader_failure_is_redacted_and_does_not_echo_text_or_paths(self):
        secret_text = "say my secret transcript"

        def fail(*args, **kwargs):
            raise RuntimeError(f"bad model {self.model}: {secret_text}")

        backend = PiperBackend(model_path=self.model, config_path=self.config, loader=fail)
        with self.assertRaises(VoiceError) as caught:
            backend.synthesize({"text": secret_text, "profile": "voice-a"})

        message = str(caught.exception)
        self.assertNotIn(secret_text, message)
        self.assertNotIn(str(self.model), message)
        self.assertNotIn(str(self.config), message)

    def test_synthesis_failure_is_redacted(self):
        secret_text = "private words"

        class FailingVoice:
            def synthesize_wav(self, text, wav_file):
                raise RuntimeError(f"failed on {text} at {self.model if False else 'internal'}")

        backend = PiperBackend(
            model_path=self.model,
            config_path=self.config,
            loader=lambda *a, **k: FailingVoice(),
        )
        with self.assertRaises(VoiceError) as caught:
            backend.synthesize({"text": secret_text, "profile": "voice-a"})
        self.assertNotIn(secret_text, str(caught.exception))

    def test_output_limit_aborts_wav_growth_inside_backend(self):
        class HugeVoice:
            def synthesize_wav(self, text, wav_file):
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(24000)
                wav_file.writeframes(b"x" * 8192)

        backend = PiperBackend(
            model_path=self.model,
            config_path=self.config,
            loader=lambda *a, **k: HugeVoice(),
            max_audio_bytes=256,
        )
        with self.assertRaisesRegex(VoiceError, "output limit"):
            backend.synthesize({"text": "hello", "profile": "voice-a"})

    def test_invalid_wav_metadata_fails_closed(self):
        class EmptyVoice:
            def synthesize_wav(self, text, wav_file):
                return None

        backend = PiperBackend(
            model_path=self.model,
            config_path=self.config,
            loader=lambda *a, **k: EmptyVoice(),
        )
        with self.assertRaisesRegex(VoiceError, "invalid WAV"):
            backend.synthesize({"text": "hello", "profile": "voice-a"})

    def test_default_loader_missing_package_fails_closed(self):
        backend = PiperBackend(
            model_path=self.model,
            config_path=self.config,
            import_module=lambda name: (_ for _ in ()).throw(ImportError("missing piper")),
        )
        with self.assertRaisesRegex(VoiceError, "unavailable"):
            backend.synthesize({"text": "hello", "profile": "voice-a"})


if __name__ == "__main__":
    unittest.main()
