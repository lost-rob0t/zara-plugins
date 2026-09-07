from __future__ import annotations

import json
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import Request, urlopen


class HomeAssistantHTTPError(RuntimeError):
    pass


class HomeAssistantHTTPTransport:
    _MAX_RESPONSE = 1024 * 1024
    _MAX_TOKEN_BYTES = 8192
    _METHODS = frozenset({"GET", "POST"})
    _BEARER_TOKEN = re.compile(r"[A-Za-z0-9\-._~+/]+={0,}\Z")

    def __init__(self, base_url: str, access_token: str, *, refresh_token=None, timeout: float = 10.0) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise HomeAssistantHTTPError("invalid-base-url")
        if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            raise HomeAssistantHTTPError("invalid-base-url")
        if parsed.path not in {"", "/"}:
            raise HomeAssistantHTTPError("invalid-base-url")
        if not self._valid_bearer_token(access_token):
            raise HomeAssistantHTTPError("invalid-access-token")
        if timeout <= 0 or timeout > 60:
            raise HomeAssistantHTTPError("invalid-timeout")
        self.base_url = base_url.rstrip("/")
        self._access_token = access_token
        self._refresh_token = refresh_token
        self.timeout = timeout

    def request(self, method: str, path: str, payload=None):
        if method not in self._METHODS:
            raise HomeAssistantHTTPError("unsupported-method")
        self._validate_path(path)
        return self._request_once(method, path, payload, allow_refresh=True)

    def _request_once(self, method: str, path: str, payload, *, allow_refresh: bool):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(urljoin(self.base_url + "/", path.lstrip("/")), data=body, method=method)
        request.add_header("Accept", "application/json")
        request.add_header("Authorization", f"Bearer {self._access_token}")
        if body is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(self._MAX_RESPONSE + 1)
        except HTTPError as error:
            if error.code == 401 and allow_refresh:
                return self._refresh_and_retry(method, path, payload)
            raise self._http_error(error.code) from None
        except (URLError, TimeoutError, socket.timeout, ConnectionError):
            raise HomeAssistantHTTPError("provider-unavailable") from None

        if len(raw) > self._MAX_RESPONSE:
            raise HomeAssistantHTTPError("response-too-large")
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise HomeAssistantHTTPError("invalid-json") from None

    def _refresh_and_retry(self, method: str, path: str, payload):
        if self._refresh_token is None:
            raise HomeAssistantHTTPError("reauth-required")
        try:
            token = self._refresh_token()
        except Exception:
            raise HomeAssistantHTTPError("reauth-required") from None
        if not self._valid_bearer_token(token):
            raise HomeAssistantHTTPError("reauth-required")
        self._access_token = token
        return self._request_once(method, path, payload, allow_refresh=False)

    @classmethod
    def _valid_bearer_token(cls, token) -> bool:
        if not isinstance(token, str) or not token:
            return False
        if len(token) > cls._MAX_TOKEN_BYTES:
            return False
        return cls._BEARER_TOKEN.fullmatch(token) is not None

    @staticmethod
    def _validate_path(path: str) -> None:
        if not isinstance(path, str) or not path.startswith("/api/") or path.startswith("//"):
            raise HomeAssistantHTTPError("invalid-request-path")
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            raise HomeAssistantHTTPError("invalid-request-path")
        decoded = unquote(parsed.path)
        segments = [segment for segment in decoded.split("/") if segment]
        if any(segment in {".", ".."} for segment in segments):
            raise HomeAssistantHTTPError("invalid-request-path")

    @staticmethod
    def _http_error(status: int) -> HomeAssistantHTTPError:
        if status == 400:
            return HomeAssistantHTTPError("bad-request")
        if status == 401:
            return HomeAssistantHTTPError("reauth-required")
        if status == 403:
            return HomeAssistantHTTPError("forbidden")
        if status == 404:
            return HomeAssistantHTTPError("not-found")
        if status == 429:
            return HomeAssistantHTTPError("rate-limited")
        if 500 <= status <= 599:
            return HomeAssistantHTTPError("provider-error")
        return HomeAssistantHTTPError(f"http-error-{status}")
