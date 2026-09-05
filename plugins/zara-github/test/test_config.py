import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_github.config import GitHubConfig, GitHubConfigError


class GitHubConfigTest(unittest.TestCase):
    def test_environment_token_is_loaded_without_echo_surface(self):
        with patch.dict(os.environ, {"ZARA_GITHUB_TOKEN": "private-token"}, clear=False):
            config = GitHubConfig.load({"owner": "lost-rob0t"})
        self.assertEqual(config.token, "private-token")
        self.assertEqual(config.owner, "lost-rob0t")

    def test_secret_file_must_be_owner_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token"
            path.write_text("private-token\n", encoding="utf-8")
            path.chmod(0o644)
            with self.assertRaisesRegex(GitHubConfigError, "0600"):
                GitHubConfig.load({"token_file": str(path)})

    def test_remote_api_base_requires_https(self):
        with self.assertRaisesRegex(GitHubConfigError, "https"):
            GitHubConfig.load({"api_base": "http://github.example/api/v3", "token": "x"})


if __name__ == "__main__":
    unittest.main()
