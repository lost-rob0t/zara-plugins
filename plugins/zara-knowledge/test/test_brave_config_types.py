from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_knowledge.brave import BraveProvider, BraveProviderError


class BraveProviderConfigTypeTests(unittest.TestCase):
    def test_rejects_non_string_api_key(self) -> None:
        for api_key in (None, True, 1, b"secret"):
            with self.subTest(api_key=api_key):
                with self.assertRaises(BraveProviderError):
                    BraveProvider(api_key=api_key)  # type: ignore[arg-type]

    def test_rejects_malformed_timeout(self) -> None:
        for timeout in (True, False, "5", None, math.nan, math.inf, -math.inf):
            with self.subTest(timeout=timeout):
                with self.assertRaises(BraveProviderError):
                    BraveProvider(api_key="secret", timeout_seconds=timeout)  # type: ignore[arg-type]

    def test_rejects_non_integer_response_bound(self) -> None:
        for limit in (True, False, 2048.5, "2048", None):
            with self.subTest(limit=limit):
                with self.assertRaises(BraveProviderError):
                    BraveProvider(api_key="secret", max_response_bytes=limit)  # type: ignore[arg-type]

    def test_accepts_typed_provider_limits(self) -> None:
        provider = BraveProvider(
            api_key="secret",
            timeout_seconds=0.25,
            max_response_bytes=2048,
        )
        self.assertEqual(0.25, provider.timeout_seconds)
        self.assertEqual(2048, provider.max_response_bytes)


if __name__ == "__main__":
    unittest.main()
