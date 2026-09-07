import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_browser.browser import BrowserError
from zara_browser.webdriver import WebDriverBrowserBackend


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.active = "win-1"
        self.handles = ["win-1"]
        self.urls = {"win-1": "https://example.test/"}
        self.titles = {"win-1": "Example"}
        self.elements = {"body": "body-1", "#search": "search-1"}
        self.text = {"body-1": "hello world"}
        self.values = {"search-1": ""}
        self.property_unavailable = set()
        self.fail_title_for = None

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if path.endswith("/window/handles"):
            return self.handles
        if path.endswith("/window") and method == "GET":
            return self.active
        if path.endswith("/window") and method == "POST":
            self.active = payload["handle"]
            return None
        if path.endswith("/window/new"):
            handle = f"win-{len(self.handles) + 1}"
            self.handles.append(handle)
            self.urls[handle] = "about:blank"
            self.titles[handle] = ""
            return {"handle": handle, "type": "tab"}
        if path.endswith("/url") and method == "GET":
            return self.urls[self.active]
        if path.endswith("/url") and method == "POST":
            self.urls[self.active] = payload["url"]
            return None
        if path.endswith("/title"):
            if self.active == self.fail_title_for:
                raise BrowserError("synthetic title failure")
            return self.titles[self.active]
        if path.endswith("/element"):
            selector = payload["value"]
            return {"element-6066-11e4-a52e-4f735466cecf": self.elements[selector]}
        if "/element/" in path and path.endswith("/text"):
            element_id = path.split("/element/", 1)[1].split("/", 1)[0]
            return self.text.get(element_id, "")
        if "/element/" in path and path.endswith("/click"):
            return None
        if "/element/" in path and path.endswith("/value"):
            element_id = path.split("/element/", 1)[1].split("/", 1)[0]
            self.values[element_id] = self.values.get(element_id, "") + payload["text"]
            return None
        if "/element/" in path and path.endswith("/property/value"):
            element_id = path.split("/element/", 1)[1].split("/", 1)[0]
            if element_id in self.property_unavailable:
                return None
            return self.values.get(element_id)
        if path.endswith("/back") or path.endswith("/forward") or path.endswith("/refresh"):
            return None
        if path.endswith("/screenshot"):
            return "ZmFrZS1wbmc="
        if path.endswith("/window") and method == "DELETE":
            self.handles.remove(self.active)
            self.active = self.handles[0] if self.handles else None
            return list(self.handles)
        raise AssertionError(f"unexpected request: {method} {path} {payload}")


class WebDriverBrowserBackendTest(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.backend = WebDriverBrowserBackend(
            "http://127.0.0.1:4444",
            "session-1",
            transport=self.transport,
        )

    def test_endpoint_must_be_loopback_http_without_credentials(self):
        for endpoint in (
            "https://127.0.0.1:4444",
            "http://example.test:4444",
            "http://user:pass@127.0.0.1:4444",
        ):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(BrowserError):
                    WebDriverBrowserBackend(endpoint, "session-1", transport=self.transport)

    def test_list_tabs_restores_active_window(self):
        self.transport.handles.append("win-2")
        self.transport.urls["win-2"] = "https://example.test/two"
        self.transport.titles["win-2"] = "Two"
        tabs = self.backend.list_tabs()
        self.assertEqual(self.transport.active, "win-1")
        self.assertEqual([tab["tab_id"] for tab in tabs], ["win-1", "win-2"])
        self.assertEqual(tabs[1]["title"], "Two")

    def test_list_tabs_restores_active_window_when_enumeration_fails(self):
        self.transport.handles.append("win-2")
        self.transport.urls["win-2"] = "https://example.test/two"
        self.transport.titles["win-2"] = "Two"
        self.transport.fail_title_for = "win-2"
        with self.assertRaisesRegex(BrowserError, "synthetic title failure"):
            self.backend.list_tabs()
        self.assertEqual(self.transport.active, "win-1")

    def test_list_tabs_rejects_excessive_handle_sets_before_enumeration(self):
        self.transport.handles = [f"win-{index}" for index in range(1, 34)]
        with self.assertRaisesRegex(BrowserError, "window handle limit"):
            self.backend.list_tabs()
        switched = [call for call in self.transport.calls if call[1].endswith("/window") and call[0] == "POST"]
        self.assertEqual(switched, [])

    def test_open_tab_navigates_new_handle_and_returns_observed_state(self):
        result = self.backend.open_tab("https://example.test/new")
        self.assertEqual(result["tab_id"], "win-2")
        self.assertEqual(result["url"], "https://example.test/new")
        self.assertEqual(self.backend.active_tab_id, "win-2")

    def test_extract_uses_native_body_text_without_javascript(self):
        result = self.backend.extract()
        self.assertEqual(result["text"], "hello world")
        self.assertEqual(result["url"], "https://example.test/")
        self.assertEqual(result["links"], [])
        self.assertFalse(any("execute" in path for _, path, _ in self.transport.calls))

    def test_click_reports_acknowledgement_without_claiming_effect_observation(self):
        clicked = self.backend.click("#search")
        self.assertTrue(clicked["acknowledged"])
        self.assertFalse(clicked["observed"])
        self.assertEqual(clicked["tab_id"], "win-1")
        self.assertEqual(clicked["url"], "https://example.test/")

    def test_type_is_observed_only_after_element_value_readback(self):
        typed = self.backend.type_text("#search", "hello")
        self.assertTrue(typed["acknowledged"])
        self.assertTrue(typed["observed"])
        self.assertEqual(typed["observed_value"], "hello")
        self.assertEqual(typed["value_length"], 5)
        self.assertFalse(typed["submitted"])
        self.assertTrue(any(path.endswith("/element/search-1/property/value") for _, path, _ in self.transport.calls))

    def test_type_does_not_claim_observation_when_value_readback_is_unavailable(self):
        self.transport.property_unavailable.add("search-1")
        typed = self.backend.type_text("#search", "hello")
        self.assertTrue(typed["acknowledged"])
        self.assertFalse(typed["observed"])
        self.assertIsNone(typed["observed_value"])

    def test_download_is_explicitly_unavailable(self):
        result = self.backend.download("https://example.test/file", "file.bin")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "webdriver-download-not-supported")

    def test_screenshot_decodes_webdriver_payload(self):
        self.assertEqual(self.backend.screenshot(), b"fake-png")


if __name__ == "__main__":
    unittest.main()
