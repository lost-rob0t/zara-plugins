from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_comms.domain import CommsDomain, CommsError


class Provider:
    def __init__(self) -> None:
        self.search_calls = 0

    def search(self, query, limit):
        self.search_calls += 1
        return []


class Resolver:
    pass


class CommsPolicyTypeTests(unittest.TestCase):
    def test_rejects_coercive_constructor_limits(self) -> None:
        for field in ("max_results", "max_body_bytes"):
            for value in (True, False, 1.5, "50", None):
                options = {"max_results": 50, "max_body_bytes": 65536, field: value}
                with self.subTest(field=field, value=value):
                    with self.assertRaises(CommsError):
                        CommsDomain({"test": Provider()}, Resolver(), **options)

    def test_rejects_coercive_search_limit_before_provider_dispatch(self) -> None:
        provider = Provider()
        comms = CommsDomain({"test": provider}, Resolver())
        for value in (True, False, 1.5, "1"):
            with self.subTest(value=value):
                with self.assertRaises(CommsError):
                    comms.search("status", limit=value)
                self.assertEqual(0, provider.search_calls)

    def test_accepts_integer_policy_inside_existing_bounds(self) -> None:
        comms = CommsDomain(
            {"test": Provider()},
            Resolver(),
            max_results=12,
            max_body_bytes=4096,
        )
        self.assertEqual(12, comms.max_results)
        self.assertEqual(4096, comms.max_body_bytes)


if __name__ == "__main__":
    unittest.main()
