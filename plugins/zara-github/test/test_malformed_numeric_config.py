import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_github.config import GitHubConfig, GitHubConfigError


class MalformedNumericConfigTests(unittest.TestCase):
    def test_rejects_malformed_numeric_config_structurally(self):
        cases = (
            {"timeout_seconds": None},
            {"timeout_seconds": "not-a-number"},
            {"max_response_bytes": None},
            {"max_response_bytes": "many"},
            {"max_results": None},
            {"max_results": "many"},
        )
        for mapping in cases:
            with self.subTest(mapping=mapping):
                with self.assertRaises(GitHubConfigError):
                    GitHubConfig.load(mapping)

    def test_preserves_valid_numeric_strings(self):
        config = GitHubConfig.load(
            {
                "timeout_seconds": "1.5",
                "max_response_bytes": "4096",
                "max_results": "5",
            }
        )
        self.assertEqual(config.timeout_seconds, 1.5)
        self.assertEqual(config.max_response_bytes, 4096)
        self.assertEqual(config.max_results, 5)


if __name__ == "__main__":
    unittest.main()
