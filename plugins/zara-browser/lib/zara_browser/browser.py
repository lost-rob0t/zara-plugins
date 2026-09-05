from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlsplit


class BrowserError(RuntimeError):
    pass


def _bounded_text(value: str, *, name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise BrowserError(f"{name} must be a string")
    if any(ord(character) < 0x20 and character not in "\t\n" for character in value):
        raise BrowserError(f"{name} contains control characters")
    if len(value.encode("utf-8")) > limit:
        raise BrowserError(f"{name} exceeds byte limit")
    return value


def _url(value: str) -> str:
    value = _bounded_text(value, name="URL", limit=2048)
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise BrowserError("browser URL must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise BrowserError("browser URL must not contain userinfo")
    return value


def _selector(value: str) -> str:
    value = _bounded_text(value, name="selector", limit=256)
    if not value.strip():
        raise BrowserError("selector must not be empty")
    return value


def _download_destination(value: str) -> str:
    value = _bounded_text(value, name="download destination", limit=256)
    path = PurePosixPath(value)
    if path.is_absolute() or not value or any(part in {"", ".", ".."} for part in path.parts):
        raise BrowserError("download destination must be a safe relative path")
    return value


@dataclass
class _FakeTab:
    tab_id: str
    history: list[str]
    index: int

    @property
    def url(self) -> str:
        return self.history[self.index]


class FakeBrowserBackend:
    def __init__(self) -> None:
        self.tabs: dict[str, _FakeTab] = {}
        self.active_tab_id: str | None = None
        self._next_tab = 1
        self.page_text = ""
        self.page_title = ""
        self.page_links: list[dict[str, str]] = []
        self.cookies: dict[str, str] = {}
        self.screenshot_supported = True

    def set_page(self, *, text: str = "", title: str = "", links=None, cookies=None) -> None:
        self.page_text = text
        self.page_title = title
        self.page_links = list(links or [])
        self.cookies = dict(cookies or {})

    def open_tab(self, url: str) -> dict[str, object]:
        tab_id = f"tab-{self._next_tab}"
        self._next_tab += 1
        self.tabs[tab_id] = _FakeTab(tab_id, [url], 0)
        self.active_tab_id = tab_id
        return self.tab(tab_id)

    def close_tab(self, tab_id: str) -> None:
        if tab_id not in self.tabs:
            raise BrowserError("unknown browser tab")
        del self.tabs[tab_id]
        if self.active_tab_id == tab_id:
            self.active_tab_id = next(iter(self.tabs), None)

    def switch_tab(self, tab_id: str) -> dict[str, object]:
        if tab_id not in self.tabs:
            raise BrowserError("unknown browser tab")
        self.active_tab_id = tab_id
        return self.tab(tab_id)

    def tab(self, tab_id: str) -> dict[str, object]:
        tab = self.tabs[tab_id]
        return {"tab_id": tab.tab_id, "url": tab.url, "title": self.page_title}

    def list_tabs(self) -> list[dict[str, object]]:
        return [self.tab(tab_id) for tab_id in self.tabs]

    def _active(self) -> _FakeTab:
        if self.active_tab_id is None or self.active_tab_id not in self.tabs:
            raise BrowserError("no active browser tab")
        return self.tabs[self.active_tab_id]

    def navigate(self, url: str) -> dict[str, object]:
        tab = self._active()
        del tab.history[tab.index + 1 :]
        tab.history.append(url)
        tab.index += 1
        return self.tab(tab.tab_id)

    def reload(self) -> dict[str, object]:
        tab = self._active()
        return self.tab(tab.tab_id)

    def back(self) -> dict[str, object]:
        tab = self._active()
        if tab.index == 0:
            raise BrowserError("browser history has no previous page")
        tab.index -= 1
        return self.tab(tab.tab_id)

    def forward(self) -> dict[str, object]:
        tab = self._active()
        if tab.index + 1 >= len(tab.history):
            raise BrowserError("browser history has no next page")
        tab.index += 1
        return self.tab(tab.tab_id)

    def extract(self) -> dict[str, object]:
        tab = self._active()
        return {
            "tab_id": tab.tab_id,
            "url": tab.url,
            "title": self.page_title,
            "text": self.page_text,
            "links": list(self.page_links),
        }

    def click(self, selector: str) -> dict[str, object]:
        tab = self._active()
        return {"action": "click", "selector": selector, "tab_id": tab.tab_id, "url": tab.url, "observed": True}

    def type_text(self, selector: str, text: str) -> dict[str, object]:
        tab = self._active()
        return {
            "action": "type",
            "selector": selector,
            "tab_id": tab.tab_id,
            "url": tab.url,
            "value_length": len(text),
            "submitted": False,
            "observed": True,
        }

    def select(self, selector: str, value: str) -> dict[str, object]:
        tab = self._active()
        return {"action": "select", "selector": selector, "tab_id": tab.tab_id, "url": tab.url, "value": value, "observed": True}

    def screenshot(self) -> bytes | None:
        self._active()
        if not self.screenshot_supported:
            return None
        return b"fake-png"

    def download(self, url: str, destination: str) -> dict[str, object]:
        self._active()
        return {"status": "accepted", "url": url, "destination": destination, "observed": True}


class UnavailableBrowserBackend:
    reason = "browser-backend-not-configured"

    def list_tabs(self) -> list[dict[str, object]]:
        return []


class BrowserSession:
    def __init__(
        self,
        backend,
        *,
        max_text_bytes: int = 65536,
        max_tabs: int = 16,
        max_input_bytes: int = 8192,
        max_screenshot_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        if not 64 <= max_text_bytes <= 1024 * 1024:
            raise BrowserError("max_text_bytes is out of range")
        if not 1 <= max_tabs <= 64:
            raise BrowserError("max_tabs is out of range")
        if not 1 <= max_input_bytes <= 65536:
            raise BrowserError("max_input_bytes is out of range")
        if not 1024 <= max_screenshot_bytes <= 8 * 1024 * 1024:
            raise BrowserError("max_screenshot_bytes is out of range")
        self.backend = backend
        self.max_text_bytes = max_text_bytes
        self.max_tabs = max_tabs
        self.max_input_bytes = max_input_bytes
        self.max_screenshot_bytes = max_screenshot_bytes

    def _require_backend(self) -> None:
        if isinstance(self.backend, UnavailableBrowserBackend):
            raise BrowserError(self.backend.reason)

    def status(self) -> dict[str, object]:
        if isinstance(self.backend, UnavailableBrowserBackend):
            return {"status": "unavailable", "reason": self.backend.reason, "tabs": [], "active_tab_id": None}
        tabs = self.backend.list_tabs()
        active_id = getattr(self.backend, "active_tab_id", None)
        active = next((tab for tab in tabs if tab.get("tab_id") == active_id), None)
        return {"status": "ready", "tabs": tabs, "active_tab_id": active_id, "active": active}

    def open_tab(self, url: str) -> dict[str, object]:
        self._require_backend()
        if len(self.backend.list_tabs()) >= self.max_tabs:
            raise BrowserError("browser tab limit reached")
        return self.backend.open_tab(_url(url))

    def close_tab(self, tab_id: str) -> dict[str, object]:
        self._require_backend()
        tab_id = _bounded_text(tab_id, name="tab id", limit=128)
        self.backend.close_tab(tab_id)
        return self.status()

    def switch_tab(self, tab_id: str) -> dict[str, object]:
        self._require_backend()
        return self.backend.switch_tab(_bounded_text(tab_id, name="tab id", limit=128))

    def navigate(self, url: str) -> dict[str, object]:
        self._require_backend()
        return self.backend.navigate(_url(url))

    def reload(self) -> dict[str, object]:
        self._require_backend()
        return self.backend.reload()

    def back(self) -> dict[str, object]:
        self._require_backend()
        return self.backend.back()

    def forward(self) -> dict[str, object]:
        self._require_backend()
        return self.backend.forward()

    def extract_text(self) -> dict[str, object]:
        self._require_backend()
        result = dict(self.backend.extract())
        text = str(result.get("text", ""))
        encoded = text.encode("utf-8")
        truncated = len(encoded) > self.max_text_bytes
        if truncated:
            encoded = encoded[: self.max_text_bytes]
            text = encoded.decode("utf-8", errors="ignore")
        links = result.get("links", [])
        if not isinstance(links, list):
            links = []
        result["text"] = text
        result["truncated"] = truncated
        result["links"] = links[:128]
        result.pop("cookies", None)
        return result

    def click(self, selector: str) -> dict[str, object]:
        self._require_backend()
        return self.backend.click(_selector(selector))

    def type_text(self, selector: str, text: str) -> dict[str, object]:
        self._require_backend()
        text = _bounded_text(text, name="typed text", limit=self.max_input_bytes)
        return self.backend.type_text(_selector(selector), text)

    def select(self, selector: str, value: str) -> dict[str, object]:
        self._require_backend()
        value = _bounded_text(value, name="selected value", limit=1024)
        return self.backend.select(_selector(selector), value)

    def screenshot(self) -> dict[str, object]:
        self._require_backend()
        payload = self.backend.screenshot()
        if payload is None:
            return {"status": "unavailable", "reason": "screenshot-not-supported"}
        if not isinstance(payload, bytes):
            raise BrowserError("browser screenshot backend returned invalid data")
        if len(payload) > self.max_screenshot_bytes:
            raise BrowserError("browser screenshot exceeds byte limit")
        return {
            "status": "ok",
            "mime_type": "image/png",
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "data_base64": base64.b64encode(payload).decode("ascii"),
        }

    def download(self, url: str, destination: str) -> dict[str, object]:
        self._require_backend()
        return self.backend.download(_url(url), _download_destination(destination))
