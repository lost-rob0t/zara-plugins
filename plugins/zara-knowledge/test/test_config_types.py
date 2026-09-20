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
        for key in ("max_response_bytes", "max_results", "wiki_max_gates"):
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

    def test_accepts_wiki_gate_and_store_configuration(self) -> None:
        config = self.load(
            {
                "wiki_store_path": "~/wiki-cache.sqlite3",
                "wiki_max_gates": 6,
                "wiki_default_gates": ["wikipedia:en", "wikidata"],
                "wiki_gates": {
                    "internal": {
                        "base_url": "http://127.0.0.1:8080",
                        "engine": "mediawiki",
                    }
                },
            }
        )
        self.assertTrue(str(config.wiki_store_path).endswith("wiki-cache.sqlite3"))
        self.assertEqual(6, config.wiki_max_gates)
        self.assertEqual(("wikipedia:en", "wikidata"), config.wiki_default_gates)
        self.assertEqual("mediawiki", config.wiki_gates["internal"]["engine"])

    def test_rejects_malformed_wiki_configuration(self) -> None:
        bad_values = (
            {"wiki_store_path": True},
            {"wiki_default_gates": 42},
            {"wiki_gates": []},
            {"wiki_gates": {"bad": "not-a-mapping"}},
            {"wiki_max_gates": 0},
            {"wiki_max_gates": 17},
        )
        for value in bad_values:
            with self.subTest(value=value):
                with self.assertRaises(KnowledgeConfigError):
                    self.load(value)


if __name__ == "__main__":
    unittest.main()
