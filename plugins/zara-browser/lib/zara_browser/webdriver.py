from __future__ import annotations

import base64
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .browser import BrowserError


_ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"
_MAX_WINDOW_HANDLES = 32


def _webdriver_endpoint(value: str) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > 512:
        raise BrowserError("WebDriver endpoint must be a bounded string")
    parsed = urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise BrowserError("WebDriver endpoint must use loopback HTTP")
    if parsed.username is not None or parsed.password is not None:
        raise BrowserError("WebDriver endpoint must not contain credentials")
    if parsed.query or parsed.fragment:
        raise BrowserError("WebDriver endpoint must not contain query or fragment")
    return value.rstrip("/")


def _session_id(value: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 256:
        raise BrowserError("WebDriver session id must be a bounded string")
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for character in value):
        raise BrowserError("WebDriver session id contains unsafe characters")
    return value


class WebDriverTransport:
    def __init__(self, endpoint: str, session_id: str, *, timeout: float = 10.0) -> None:
        self.endpoint = _webdriver_endpoint(endpoint)
        self.session_id = _session_id(session_id)
        self.timeout = timeout

    def request(self, method: str, path: str, payload=None):
        url = f"{self.endpoint}{path}"
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(url, data=body, method=method)
        request.add_header("Accept", "application/json")
        if body is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(1024 * 1024 + 1)
        except HTTPError as error:
            raise BrowserError(f"WebDriver HTTP error: {error.code}") from error
        except (URLError, TimeoutError) as error:
            raise BrowserError("WebDriver backend unavailable") from error
        if len(raw) > 1024 * 1024:
            raise BrowserError("WebDriver response exceeds byte limit")
        if not raw:
            return None
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BrowserError("WebDriver returned invalid JSON") from error
        if not isinstance(document, dict) or "value" not in document:
            raise BrowserError("WebDriver returned malformed response")
        value = document["value"]
        if isinstance(value, dict) and value.get("error"):
            message = value.get("message")
            raise BrowserError(f"WebDriver error: {message or value['error']}")
        return value


class WebDriverBrowserBackend:
    def __init__(self, endpoint: str, session_id: str, *, transport=None) -> None:
        self.endpoint = _webdriver_endpoint(endpoint)
        self.session_id = _session_id(session_id)
        self.transport = transport or WebDriverTransport(self.endpoint, self.session_id)
        self._session_path = f"/session/{self.session_id}"

    def _request(self, method: str, suffix: str, payload=None):
        return self.transport.request(method, f"{self._session_path}{suffix}", payload)

    @property
    def active_tab_id(self) -> str | None:
        value = self._request("GET", "/window")
        return value if isinstance(value, str) else None

    def _switch(self, tab_id: str) -> None:
        self._request("POST", "/window", {"handle": tab_id})

    def _tab(self, tab_id: str) -> dict[str, object]:
        self._switch(tab_id)
        url = self._request("GET", "/url")
        title = self._request("GET", "/title")
        return {
            "tab_id": tab_id,
            "url": url if isinstance(url, str) else "",
            "title": title if isinstance(title, str) else "",
        }

    def list_tabs(self) -> list[dict[str, object]]:
        active = self.active_tab_id
        handles = self._request("GET", "/window/handles")
        if not isinstance(handles, list) or not all(isinstance(handle, str) for handle in handles):
            raise BrowserError("WebDriver returned invalid window handles")
        if len(handles) > _MAX_WINDOW_HANDLES:
            raise BrowserError("WebDriver window handle limit exceeded")
        if len(set(handles)) != len(handles):
            raise BrowserError("WebDriver returned duplicate window handles")
        if any(len(handle.encode("utf-8")) > 256 for handle in handles):
            raise BrowserError("WebDriver returned oversized window handle")

        tabs: list[dict[str, object]] = []
        primary_error: Exception | None = None
        try:
            for handle in handles:
                tabs.append(self._tab(handle))
        except Exception as error:
            primary_error = error

        if active in handles:
            try:
                self._switch(active)
            except Exception as restoration_error:
                if primary_error is not None:
                    raise primary_error from restoration_error
                raise

        if primary_error is not None:
            raise primary_error
        return tabs

    def open_tab(self, url: str) -> dict[str, object]:
        created = self._request("POST", "/window/new", {"type": "tab"})
        if not isinstance(created, dict) or not isinstance(created.get("handle"), str):
            raise BrowserError("WebDriver did not return a new tab handle")
        handle = created["handle"]
        self._switch(handle)
        self._request("POST", "/url", {"url": url})
        return self._tab(handle)

    def close_tab(self, tab_id: str) -> None:
        self._switch(tab_id)
        self._request("DELETE", "/window")

    def switch_tab(self, tab_id: str) -> dict[str, object]:
        self._switch(tab_id)
        return self._tab(tab_id)

    def navigate(self, url: str) -> dict[str, object]:
        active = self.active_tab_id
        if active is None:
            raise BrowserError("no active browser tab")
        self._request("POST", "/url", {"url": url})
        return self._tab(active)

    def reload(self) -> dict[str, object]:
        active = self.active_tab_id
        if active is None:
            raise BrowserError("no active browser tab")
        self._request("POST", "/refresh", {})
        return self._tab(active)

    def back(self) -> dict[str, object]:
        active = self.active_tab_id
        if active is None:
            raise BrowserError("no active browser tab")
        self._request("POST", "/back", {})
        return self._tab(active)

    def forward(self) -> dict[str, object]:
        active = self.active_tab_id
        if active is None:
            raise BrowserError("no active browser tab")
        self._request("POST", "/forward", {})
        return self._tab(active)

    def _element(self, selector: str) -> str:
        value = self._request("POST", "/element", {"using": "css selector", "value": selector})
        if not isinstance(value, dict) or not isinstance(value.get(_ELEMENT_KEY), str):
            raise BrowserError("WebDriver returned invalid element reference")
        return value[_ELEMENT_KEY]

    def extract(self) -> dict[str, object]:
        active = self.active_tab_id
        if active is None:
            raise BrowserError("no active browser tab")
        body = self._element("body")
        text = self._request("GET", f"/element/{body}/text")
        tab = self._tab(active)
        return {
            **tab,
            "text": text if isinstance(text, str) else "",
            "links": [],
        }

    def click(self, selector: str) -> dict[str, object]:
        element = self._element(selector)
        self._request("POST", f"/element/{element}/click", {})
        active = self.active_tab_id
        url = self._request("GET", "/url")
        return {
            "action": "click",
            "selector": selector,
            "tab_id": active,
            "url": url if isinstance(url, str) else "",
            "acknowledged": True,
            "observed": False,
            "observation": "post-action-tab-state-only",
        }

    def type_text(self, selector: str, text: str) -> dict[str, object]:
        element = self._element(selector)
        before_value = self._request("GET", f"/element/{element}/property/value")
        self._request("POST", f"/element/{element}/value", {"text": text})
        observed_value = self._request("GET", f"/element/{element}/property/value")
        active = self.active_tab_id
        url = self._request("GET", "/url")
        observed = (
            bool(text)
            and isinstance(before_value, str)
            and isinstance(observed_value, str)
            and observed_value != before_value
            and observed_value.endswith(text)
        )
        return {
            "action": "type",
            "selector": selector,
            "tab_id": active,
            "url": url if isinstance(url, str) else "",
            "value_length": len(text),
            "submitted": False,
            "acknowledged": True,
            "observed": observed,
            "observed_value": observed_value if isinstance(observed_value, str) else None,
            "observation": "element-value-before-after" if observed else "element-value-not-verified",
        }

    def select(self, selector: str, value: str) -> dict[str, object]:
        return {
            "status": "unavailable",
            "reason": "webdriver-select-not-supported",
            "selector": selector,
            "value": value,
        }

    def screenshot(self) -> bytes:
        payload = self._request("GET", "/screenshot")
        if not isinstance(payload, str):
            raise BrowserError("WebDriver returned invalid screenshot")
        try:
            return base64.b64decode(payload, validate=True)
        except ValueError as error:
            raise BrowserError("WebDriver returned invalid screenshot encoding") from error

    def download(self, url: str, destination: str) -> dict[str, object]:
        return {
            "status": "unavailable",
            "reason": "webdriver-download-not-supported",
            "url": url,
            "destination": destination,
        }
