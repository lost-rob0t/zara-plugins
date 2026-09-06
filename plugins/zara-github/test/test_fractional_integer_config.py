import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_github.config import GitHubConfig, GitHubConfigError


class FractionalIntegerConfigTests(unittest.TestCase):
    def test_rejects_fractional_integer_only_limits(self):
        for key in ("max_response_bytes", "max_results"):
            with self.subTest(key=key):
                with self.assertRaises(GitHubConfigError):
                    GitHubConfig.load({key: 4096.5 if key == "max_response_bytes" else 5.5})

    def test_preserves_integer_strings(self):
        config = GitHubConfig.load({"max_response_bytes": "4096", "max_results": "5"})
        self.assertEqual(config.max_response_bytes, 4096)
        self.assertEqual(config.max_results, 5)


if __name__ == "__main__":
    unittest.main()
