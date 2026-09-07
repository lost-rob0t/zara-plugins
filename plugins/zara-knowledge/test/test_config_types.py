from __future__ import annotations

import math
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_knowledge.config import KnowledgeConfig, KnowledgeConfigError


class KnowledgeConfigTypeTests(unittest.TestCase):
    def load(self, mapping: dict[str, object]) -> KnowledgeConfig:
        with patch.dict(os.environ, {}, clear=True):
            return KnowledgeConfig.load(mapping)

    def test_rejects_non_string_provider_and_key(self) -> None:
        for key in ("default_provider", "brave_api_key"):
            for value in (None, True, 1, b"value"):
                with self.subTest(key=key, value=value):
                    with self.assertRaises(KnowledgeConfigError):
                        self.load({key: value})

    def test_rejects_non_pathlike_credential_file(self) -> None:
        for value in (True, 1, b"secret"):
            with self.subTest(value=value):
                with self.assertRaises(KnowledgeConfigError):
                    self.load({"brave_api_key_file": value})

    def test_rejects_malformed_timeout(self) -> None:
        for value in (True, False, "5", None, math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaises(KnowledgeConfigError):
                    self.load({"timeout_seconds": value})

    def test_rejects_non_integer_limits(self) -> None:
        for key in ("max_response_bytes", "max_results"):
            for value in (True, False, 2.5, "2", None):
                with self.subTest(key=key, value=value):
                    with self.assertRaises(KnowledgeConfigError):
                        self.load({key: value})

    def test_accepts_typed_configuration(self) -> None:
        config = self.load(
            {
                "default_provider": "brave",
                "brave_api_key": "secret",
                "timeout_seconds": 0.25,
                "max_response_bytes": 2048,
                "max_results": 2,
            }
        )
        self.assertEqual("secret", config.brave_api_key)
        self.assertEqual(0.25, config.timeout_seconds)
        self.assertEqual(2048, config.max_response_bytes)
        self.assertEqual(2, config.max_results)


if __name__ == "__main__":
    unittest.main()
