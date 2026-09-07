from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_media.domain import MediaDomain, MediaError


class ConstructorPolicyTypeTests(unittest.TestCase):
    def test_rejects_coercive_queue_limit_descriptors(self) -> None:
        for value in (True, False, 1.5, "8", None):
            with self.subTest(value=value):
                with self.assertRaises(MediaError):
                    MediaDomain(object(), max_queue_items=value)

    def test_rejects_coercive_search_limit_descriptors(self) -> None:
        for value in (True, False, 1.5, "4", None):
            with self.subTest(value=value):
                with self.assertRaises(MediaError):
                    MediaDomain(object(), max_search_results=value)

    def test_accepts_integer_limits_inside_existing_bounds(self) -> None:
        media = MediaDomain(object(), max_queue_items=8, max_search_results=4)
        self.assertEqual(8, media.max_queue_items)
        self.assertEqual(4, media.max_search_results)


if __name__ == "__main__":
    unittest.main()
