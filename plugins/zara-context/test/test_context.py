import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_context.store import ContextError, ContextStore


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class ContextStoreTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.store = ContextStore(clock=self.clock, default_ttl=10.0)

    def test_update_retains_source_timestamp_confidence_and_freshness(self):
        self.store.update("project", {"id": "zara", "path": "/work/zara"}, source="emacs", confidence=0.9)
        result = self.store.current(["project"])
        self.assertEqual(len(result["items"]), 1)
        item = result["items"][0]
        self.assertEqual(item["source"], "emacs")
        self.assertEqual(item["observed_at"], 100.0)
        self.assertFalse(item["stale"])
        self.assertEqual(item["confidence"], 0.9)

    def test_expired_context_is_explicitly_stale_not_reused_as_fresh(self):
        self.store.update("clipboard", {"kind": "text", "content": "bounded"}, source="desktop", ttl=2.0)
        self.clock.now = 103.0
        result = self.store.current(["clipboard"])
        self.assertEqual(result["items"], [])
        self.assertEqual(len(result["stale"]), 1)
        self.assertTrue(result["stale"][0]["stale"])

    def test_categories_are_filtered_and_unknown_categories_fail(self):
        self.store.update("file", {"path": "/tmp/a"}, source="editor")
        self.store.update("workspace", {"name": "dev"}, source="desktop")
        result = self.store.current(["file"])
        self.assertEqual([item["category"] for item in result["items"]], ["file"])
        with self.assertRaises(ContextError):
            self.store.current(["secret-memory-dump"])

    def test_payload_and_ttl_are_bounded(self):
        with self.assertRaises(ContextError):
            self.store.update("selection", {"text": "x" * 9000}, source="editor")
        with self.assertRaises(ContextError):
            self.store.update("file", {"path": "/tmp/a"}, source="editor", ttl=99999)

    def test_rejects_malformed_default_ttl(self):
        for value in (True, False, "10", None, math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaises(ContextError):
                    ContextStore(clock=self.clock, default_ttl=value)

    def test_rejects_malformed_update_freshness_values_before_storage(self):
        malformed = (True, False, "1", object(), math.nan, math.inf, -math.inf)
        for key in ("ttl", "confidence"):
            for value in malformed:
                with self.subTest(key=key, value=value):
                    store = ContextStore(clock=self.clock, default_ttl=10.0)
                    kwargs = {key: value}
                    with self.assertRaises(ContextError):
                        store.update("file", {"path": "/tmp/a"}, source="editor", **kwargs)
                    self.assertEqual(store.current()["items"], [])

    def test_accepts_finite_numeric_freshness_values(self):
        store = ContextStore(clock=self.clock, default_ttl=10)
        item = store.update(
            "file",
            {"path": "/tmp/a"},
            source="editor",
            confidence=0.5,
            ttl=2,
        )
        self.assertEqual(item.confidence, 0.5)
        self.assertEqual(item.expires_at, 102.0)

    def test_clear_expired_removes_only_expired_context(self):
        self.store.update("file", {"path": "/tmp/a"}, source="editor", ttl=2)
        self.store.update("project", {"id": "p"}, source="editor", ttl=20)
        self.clock.now = 103
        self.assertEqual(self.store.clear_expired(), 1)
        result = self.store.current()
        self.assertEqual([item["category"] for item in result["items"]], ["project"])


if __name__ == "__main__":
    unittest.main()
