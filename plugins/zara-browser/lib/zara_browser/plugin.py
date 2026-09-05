from __future__ import annotations

import json

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .browser import BrowserSession, UnavailableBrowserBackend


PLUGIN_VERSION = "0.1.0"


class ZaraBrowserPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-browser",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Persistent bounded browser-session abstraction",
    )

    def __init__(self, backend=None) -> None:
        self.session = BrowserSession(backend or UnavailableBrowserBackend())

    def start(self, runtime) -> None:
        return None

    def stop(self) -> None:
        return None

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def status(self) -> str:
        return self._json(self.session.status())

    def open_tab(self, url: str) -> str:
        return self._json(self.session.open_tab(url))

    def close_tab(self, tab_id: str) -> str:
        return self._json(self.session.close_tab(tab_id))

    def switch_tab(self, tab_id: str) -> str:
        return self._json(self.session.switch_tab(tab_id))

    def navigate(self, url: str) -> str:
        return self._json(self.session.navigate(url))

    def reload(self) -> str:
        return self._json(self.session.reload())

    def back(self) -> str:
        return self._json(self.session.back())

    def forward(self) -> str:
        return self._json(self.session.forward())

    def extract(self) -> str:
        return self._json(self.session.extract_text())

    def click(self, selector: str) -> str:
        return self._json(self.session.click(selector))

    def type_text(self, selector: str, text: str) -> str:
        return self._json(self.session.type_text(selector, text))

    def select(self, selector: str, value: str) -> str:
        return self._json(self.session.select(selector, value))

    def screenshot(self) -> str:
        return self._json(self.session.screenshot())

    def download(self, url: str, destination: str) -> str:
        return self._json(self.session.download(url, destination))

    def tools(self):
        return (
            StructuredTool.from_function(
                func=self.status,
                name="browser.status",
                description="Return current persistent browser session and tab state.",
            ),
            StructuredTool.from_function(
                func=self.open_tab,
                name="browser.tab.open",
                description="Open a bounded HTTP(S) tab.",
            ),
            StructuredTool.from_function(
                func=self.close_tab,
                name="browser.tab.close",
                description="Close a known browser tab by id.",
            ),
            StructuredTool.from_function(
                func=self.switch_tab,
                name="browser.tab.switch",
                description="Switch the active browser tab by id.",
            ),
            StructuredTool.from_function(
                func=self.navigate,
                name="browser.navigate",
                description="Navigate the active tab to a bounded HTTP(S) URL.",
            ),
            StructuredTool.from_function(
                func=self.reload,
                name="browser.reload",
                description="Reload the active browser tab.",
            ),
            StructuredTool.from_function(
                func=self.back,
                name="browser.back",
                description="Navigate backward in active-tab history.",
            ),
            StructuredTool.from_function(
                func=self.forward,
                name="browser.forward",
                description="Navigate forward in active-tab history.",
            ),
            StructuredTool.from_function(
                func=self.extract,
                name="browser.extract",
                description="Return bounded page text, metadata, and links without cookies or credentials.",
            ),
            StructuredTool.from_function(
                func=self.click,
                name="browser.click",
                description="Click a bounded selector and return backend-observed evidence.",
            ),
            StructuredTool.from_function(
                func=self.type_text,
                name="browser.type",
                description="Type bounded text into a selector without implicit form submission.",
            ),
            StructuredTool.from_function(
                func=self.select,
                name="browser.select",
                description="Select a bounded value through a bounded selector.",
            ),
            StructuredTool.from_function(
                func=self.screenshot,
                name="browser.screenshot",
                description="Capture a bounded active-page PNG when the configured backend supports it.",
            ),
            StructuredTool.from_function(
                func=self.download,
                name="browser.download",
                description="Request a download to a safe relative destination under the configured backend policy.",
            ),
        )


def create_plugin():
    return ZaraBrowserPlugin()
