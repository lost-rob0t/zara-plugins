from __future__ import annotations

import math
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_starintel_server.config import StarIntelConfig, StarIntelConfigError


class StarIntelNumericConfigTypeTests(unittest.TestCase):
    def load(self, mapping: dict[str, object]) -> StarIntelConfig:
        with patch.dict(os.environ, {}, clear=True):
            return StarIntelConfig.load(mapping)

    def test_rejects_malformed_timeout(self) -> None:
        for timeout in (True, False, "5", None, math.nan, math.inf, -math.inf):
            with self.subTest(timeout=timeout):
                with self.assertRaises(StarIntelConfigError):
                    self.load({"timeout_seconds": timeout})

    def test_rejects_non_integer_byte_limits(self) -> None:
        for key in ("max_request_bytes", "max_response_bytes"):
            for value in (True, False, 2048.5, "2048", None):
                with self.subTest(key=key, value=value):
                    with self.assertRaises(StarIntelConfigError):
                        self.load({key: value})

    def test_accepts_typed_numeric_limits(self) -> None:
        config = self.load(
            {
                "timeout_seconds": 0.25,
                "max_request_bytes": 2048,
                "max_response_bytes": 4096,
            }
        )
        self.assertEqual(0.25, config.timeout_seconds)
        self.assertEqual(2048, config.max_request_bytes)
        self.assertEqual(4096, config.max_response_bytes)


if __name__ == "__main__":
    unittest.main()
