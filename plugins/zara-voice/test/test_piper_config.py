import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "zara-plugin"))

import zara_voice_entrypoint
from zara_voice.domain import VoiceError


PIPER_ENV = {
    "ZARA_VOICE_PIPER_MODEL": "",
    "ZARA_VOICE_PIPER_CONFIG": "",
    "ZARA_VOICE_PIPER_PROFILE": "",
    "ZARA_VOICE_PIPER_LANGUAGE": "",
}


class PiperDiscoveryConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.model = root / "private-voice.onnx"
        self.config = root / "private-voice.onnx.json"
        self.model.write_bytes(b"model")
        self.config.write_text("{}", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def _env(self, **updates):
        values = dict(PIPER_ENV)
        values.update(updates)
        return patch.dict(os.environ, values, clear=False)

    def test_absent_piper_config_preserves_default_unavailable_state(self):
        with self._env():
            plugin = zara_voice_entrypoint.create_plugin()

        self.assertEqual(plugin.backends, {})
        self.assertEqual(
            json.loads(plugin.status()),
            {"status": "unavailable", "reason": "tts-backend-not-configured"},
        )
        self.assertEqual(json.loads(plugin.profiles()), [])

    def test_explicit_model_and_config_register_one_reachable_local_profile(self):
        with self._env(
            ZARA_VOICE_PIPER_MODEL=str(self.model),
            ZARA_VOICE_PIPER_CONFIG=str(self.config),
            ZARA_VOICE_PIPER_PROFILE="mara-local",
            ZARA_VOICE_PIPER_LANGUAGE="en-US",
        ):
            plugin = zara_voice_entrypoint.create_plugin()

        self.assertEqual(set(plugin.backends), {"piper-local"})
        backend = plugin.backends["piper-local"]
        self.assertEqual(backend.locality, "local")
        self.assertFalse(backend._use_cuda)
        self.assertEqual(
            json.loads(plugin.profiles()),
            [
                {
                    "backend": "piper-local",
                    "backend_profile": "mara-local",
                    "capabilities": [],
                    "language": "en-US",
                    "locality": "local",
                    "name": "mara-local",
                }
            ],
        )

    def test_incomplete_or_missing_file_config_fails_closed_without_path_leakage(self):
        with self._env(ZARA_VOICE_PIPER_MODEL=str(self.model)):
            with self.assertRaises(VoiceError) as caught:
                zara_voice_entrypoint.create_plugin()
        self.assertNotIn(str(self.model), str(caught.exception))

        missing = self.model.with_name("secret-missing.onnx")
        with self._env(
            ZARA_VOICE_PIPER_MODEL=str(missing),
            ZARA_VOICE_PIPER_CONFIG=str(self.config),
        ):
            with self.assertRaises(VoiceError) as caught:
                zara_voice_entrypoint.create_plugin()
        self.assertNotIn(str(missing), str(caught.exception))
        self.assertNotIn(str(self.config), str(caught.exception))

    def test_profile_defaults_are_bounded_and_do_not_enable_cuda_or_downloads(self):
        with self._env(
            ZARA_VOICE_PIPER_MODEL=str(self.model),
            ZARA_VOICE_PIPER_CONFIG=str(self.config),
        ):
            plugin = zara_voice_entrypoint.create_plugin()

        backend = plugin.backends["piper-local"]
        self.assertFalse(backend._use_cuda)
        self.assertEqual(backend._voice, None)
        profiles = json.loads(plugin.profiles())
        self.assertEqual(profiles[0]["name"], "piper-local")
        self.assertEqual(profiles[0]["backend_profile"], "piper-local")


if __name__ == "__main__":
    unittest.main()
