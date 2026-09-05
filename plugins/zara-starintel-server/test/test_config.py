import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_starintel_server.config import StarIntelConfig, StarIntelConfigError


class StarIntelConfigTest(unittest.TestCase):
    def test_remote_http_requires_explicit_opt_in(self):
        with self.assertRaisesRegex(StarIntelConfigError, "remote HTTP"):
            StarIntelConfig.load({"base_url": "http://starintel.example"})

        config = StarIntelConfig.load(
            {
                "base_url": "http://starintel.example",
                "allow_insecure_http": True,
            }
        )
        self.assertEqual(config.base_url, "http://starintel.example")

    def test_loopback_http_is_allowed(self):
        config = StarIntelConfig.load({"base_url": "http://127.0.0.1:5000/"})
        self.assertEqual(config.base_url, "http://127.0.0.1:5000")

    def test_url_rejects_credentials_query_and_fragment(self):
        invalid = (
            "https://user:pass@starintel.example",
            "https://starintel.example?token=nope",
            "https://starintel.example/#fragment",
        )
        for base_url in invalid:
            with self.subTest(base_url=base_url):
                with self.assertRaises(StarIntelConfigError):
                    StarIntelConfig.load({"base_url": base_url})

    def test_secrets_load_from_environment_without_repr_exposure(self):
        environment = {
            "ZARA_STARINTEL_API_KEY": "api-secret",
            "ZARA_STARINTEL_BOOTSTRAP_SECRET": "bootstrap-secret",
        }
        with patch.dict(os.environ, environment, clear=True):
            config = StarIntelConfig.load({"base_url": "https://starintel.example"})

        self.assertEqual(config.api_key, "api-secret")
        self.assertEqual(config.bootstrap_secret, "bootstrap-secret")
        self.assertNotIn("api-secret", repr(config))
        self.assertNotIn("bootstrap-secret", repr(config))

    def test_mode_0600_secret_files_are_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            api_key_file = root / "api-key"
            bootstrap_file = root / "bootstrap-secret"
            api_key_file.write_text("file-api-key\n", encoding="utf-8")
            bootstrap_file.write_text("file-bootstrap\n", encoding="utf-8")
            api_key_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
            bootstrap_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
            environment = {
                "ZARA_STARINTEL_API_KEY_FILE": str(api_key_file),
                "ZARA_STARINTEL_BOOTSTRAP_SECRET_FILE": str(bootstrap_file),
            }
            with patch.dict(os.environ, environment, clear=True):
                config = StarIntelConfig.load(
                    {"base_url": "https://starintel.example"}
                )

        self.assertEqual(config.api_key, "file-api-key")
        self.assertEqual(config.bootstrap_secret, "file-bootstrap")

    def test_permissive_secret_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "api-key"
            key_file.write_text("secret", encoding="utf-8")
            key_file.chmod(0o644)
            with patch.dict(
                os.environ,
                {"ZARA_STARINTEL_API_KEY_FILE": str(key_file)},
                clear=True,
            ):
                with self.assertRaisesRegex(StarIntelConfigError, "mode 0600"):
                    StarIntelConfig.load(
                        {"base_url": "https://starintel.example"}
                    )

    def test_limits_are_validated(self):
        invalid = (
            {"timeout_seconds": 0},
            {"max_request_bytes": 0},
            {"max_response_bytes": 512},
        )
        for values in invalid:
            with self.subTest(values=values):
                with self.assertRaises(StarIntelConfigError):
                    StarIntelConfig.load(values)


if __name__ == "__main__":
    unittest.main()
