import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_browser.browser import BrowserError, BrowserSession, FakeBrowserBackend


class BrowserSessionTest(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBrowserBackend()
        self.session = BrowserSession(self.backend, max_text_bytes=128, max_tabs=4)

    def test_tabs_persist_across_operations(self):
        first = self.session.open_tab("https://example.test/a")
        second = self.session.open_tab("https://example.test/b")
        self.session.switch_tab(first["tab_id"])
        state = self.session.status()
        self.assertEqual(state["active_tab_id"], first["tab_id"])
        self.assertEqual(len(state["tabs"]), 2)
        self.assertEqual(second["url"], "https://example.test/b")

    def test_navigation_and_history_are_structured(self):
        tab = self.session.open_tab("https://example.test/a")
        self.session.navigate("https://example.test/b")
        self.assertEqual(self.session.status()["active"]["url"], "https://example.test/b")
        self.session.back()
        self.assertEqual(self.session.status()["active"]["url"], tab["url"])
        self.session.forward()
        self.assertEqual(self.session.status()["active"]["url"], "https://example.test/b")

    def test_extract_text_is_bounded_and_does_not_expose_cookie_material(self):
        self.session.open_tab("https://example.test/a")
        self.backend.set_page(text="x" * 512, title="A", cookies={"session": "secret"})
        result = self.session.extract_text()
        self.assertLessEqual(len(result["text"].encode("utf-8")), 128)
        self.assertTrue(result["truncated"])
        self.assertNotIn("cookies", result)
        self.assertNotIn("secret", repr(result))

    def test_click_and_type_return_observed_evidence_without_implicit_submit(self):
        self.session.open_tab("https://example.test/form")
        clicked = self.session.click("#search")
        typed = self.session.type_text("#search", "hello")
        self.assertEqual(clicked["action"], "click")
        self.assertEqual(typed["action"], "type")
        self.assertEqual(typed["value_length"], 5)
        self.assertFalse(typed["submitted"])

    def test_selectors_urls_tabs_and_download_destination_are_bounded(self):
        with self.assertRaises(BrowserError):
            self.session.open_tab("file:///etc/passwd")
        with self.assertRaises(BrowserError):
            self.session.open_tab("https://user:pass@example.test/")
        for index in range(4):
            if index >= len(self.session.status()["tabs"]):
                self.session.open_tab(f"https://example.test/{index}")
        with self.assertRaises(BrowserError):
            self.session.open_tab("https://example.test/overflow")
        with self.assertRaises(BrowserError):
            self.session.click("x" * 300)
        with self.assertRaises(BrowserError):
            self.session.download("https://example.test/a", "../../escape")

    def test_unsupported_backend_feature_degrades_explicitly(self):
        self.session.open_tab("https://example.test/a")
        self.backend.screenshot_supported = False
        result = self.session.screenshot()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "screenshot-not-supported")


if __name__ == "__main__":
    unittest.main()
