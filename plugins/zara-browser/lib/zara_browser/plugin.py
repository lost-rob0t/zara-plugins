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
    def _json(value) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def tools(self):
        return (
            StructuredTool.from_function(func=lambda: self._json(self.session.status()), name="browser.status", description="Return current persistent browser session and tab state."),
            StructuredTool.from_function(func=lambda url: self._json(self.session.open_tab(url)), name="browser.tab.open", description="Open a bounded HTTP(S) tab."),
            StructuredTool.from_function(func=lambda tab_id: self._json(self.session.close_tab(tab_id)), name="browser.tab.close", description="Close a known browser tab by id."),
            StructuredTool.from_function(func=lambda tab_id: self._json(self.session.switch_tab(tab_id)), name="browser.tab.switch", description="Switch the active browser tab by id."),
            StructuredTool.from_function(func=lambda url: self._json(self.session.navigate(url)), name="browser.navigate", description="Navigate the active tab to a bounded HTTP(S) URL."),
            StructuredTool.from_function(func=lambda: self._json(self.session.reload()), name="browser.reload", description="Reload the active browser tab."),
            StructuredTool.from_function(func=lambda: self._json(self.session.back()), name="browser.back", description="Navigate backward in active-tab history."),
            StructuredTool.from_function(func=lambda: self._json(self.session.forward()), name="browser.forward", description="Navigate forward in active-tab history."),
            StructuredTool.from_function(func=lambda: self._json(self.session.extract_text()), name="browser.extract", description="Return bounded page text, metadata, and links without cookies or credentials."),
            StructuredTool.from_function(func=lambda selector: self._json(self.session.click(selector)), name="browser.click", description="Click a bounded selector and return backend-observed evidence."),
            StructuredTool.from_function(func=lambda selector, text: self._json(self.session.type_text(selector, text)), name="browser.type", description="Type bounded text into a selector without implicit form submission."),
            StructuredTool.from_function(func=lambda selector, value: self._json(self.session.select(selector, value)), name="browser.select", description="Select a bounded value through a bounded selector."),
            StructuredTool.from_function(func=lambda: self._json(self.session.screenshot()), name="browser.screenshot", description="Capture a bounded active-page PNG when the configured backend supports it."),
            StructuredTool.from_function(func=lambda url, destination: self._json(self.session.download(url, destination)), name="browser.download", description="Request a download to a safe relative destination under the configured backend policy."),
        )


def create_plugin():
    return ZaraBrowserPlugin()
