import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_persona_service.config import PersonaConfig


class PersonaConfigTest(unittest.TestCase):
    def test_defaults_are_empty_and_prolog_is_disabled(self):
        config = PersonaConfig.load({}, environ={})
        self.assertTrue(config.enabled)
        self.assertEqual(config.prompt, "")
        self.assertIsNone(config.prompt_file)
        self.assertFalse(config.prolog_enabled)
        self.assertIsNone(config.prolog_file)

    def test_environment_can_enable_private_prolog_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "persona.pl"
            path.write_text(":- module(zara_persona, [context/1]).\ncontext(\"x\").\n")
            config = PersonaConfig.load(
                {},
                environ={
                    "ZARA_PERSONA_PROLOG_ENABLED": "true",
                    "ZARA_PERSONA_PROLOG_FILE": str(path),
                },
            )
            config.validate_files()
            self.assertTrue(config.prolog_enabled)
            self.assertEqual(config.prolog_file, path.resolve())

    def test_explicit_configuration_wins_over_environment(self):
        config = PersonaConfig.load(
            {"prolog_enabled": False},
            environ={"ZARA_PERSONA_PROLOG_ENABLED": "true"},
        )
        self.assertFalse(config.prolog_enabled)

    def test_missing_enabled_prolog_file_is_rejected(self):
        config = PersonaConfig.load({"prolog_enabled": True}, environ={})
        with self.assertRaisesRegex(ValueError, "prolog_file is required"):
            config.validate_files()


if __name__ == "__main__":
    unittest.main()
