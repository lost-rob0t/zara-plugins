from __future__ import annotations

import math
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_agent_zero_service.config import AgentZeroConfig, AgentZeroConfigError


class AgentZeroConfigTypeTests(unittest.TestCase):
    def load(self, mapping: dict[str, object]) -> AgentZeroConfig:
        with patch.dict(os.environ, {}, clear=True):
            return AgentZeroConfig.load(mapping)

    def test_rejects_non_string_url_and_api_key(self) -> None:
        for key in ("base_url", "api_key"):
            for value in (None, True, 1, b"value"):
                with self.subTest(key=key, value=value):
                    with self.assertRaises(AgentZeroConfigError):
                        self.load({key: value})

    def test_rejects_malformed_timeout(self) -> None:
        for value in (True, False, "5", None, math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaises(AgentZeroConfigError):
                    self.load({"timeout_seconds": value})

    def test_rejects_non_integer_limits(self) -> None:
        for key in ("max_message_chars", "max_response_bytes"):
            for value in (True, False, 2048.5, "2048", None):
                with self.subTest(key=key, value=value):
                    with self.assertRaises(AgentZeroConfigError):
                        self.load({key: value})

    def test_accepts_typed_configuration(self) -> None:
        config = self.load(
            {
                "base_url": "http://127.0.0.1:50001",
                "api_key": "secret",
                "timeout_seconds": 0.25,
                "max_message_chars": 2048,
                "max_response_bytes": 4096,
            }
        )
        self.assertEqual("secret", config.api_key)
        self.assertEqual(0.25, config.timeout_seconds)
        self.assertEqual(2048, config.max_message_chars)
        self.assertEqual(4096, config.max_response_bytes)


if __name__ == "__main__":
    unittest.main()
