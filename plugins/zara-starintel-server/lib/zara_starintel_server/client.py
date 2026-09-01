"""Bounded StarIntel Server HTTP client."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping

from .config import StarIntelConfig


ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
BLOCKED_HEADERS = frozenset(
    {
        "authorization",
        "cookie",
        "host",
        "proxy-authorization",
        "x-star-bootstrap-secret",
    }
)
SAFE_RESPONSE_HEADERS = frozenset(
    {
        "cache-control",
        "content-type",
        "location",
        "retry-after",
        "x-correlation-id",
        "x-request-id",
    }
)
HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_|~-]+$")


class StarIntelError(RuntimeError):
    pass


class StarIntelClient:
    def __init__(
        self,
        config: StarIntelConfig,
        *,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.config = config
        self._opener = opener
        self._manifest_cache: dict[str, Any] | None = None

    def _require_ready(self) -> None:
        if not self.config.enabled:
            raise StarIntelError("StarIntel Server plugin is disabled")
        if not self.config.base_url:
            raise StarIntelError("StarIntel Server base_url is not configured")

    def _request_url(
        self,
        path: str,
        query: Mapping[str, Any] | None,
    ) -> str:
        text = str(path)
        parsed = urllib.parse.urlsplit(text)
        if (
            not text.startswith("/")
            or text.startswith("//")
            or parsed.scheme
            or parsed.netloc
            or parsed.query
            or parsed.fragment
            or "\\" in text
            or any(ord(character) < 32 for character in text)
        ):
            raise StarIntelError(
                "path must be an absolute same-origin path without query or fragment"
            )
        url = f"{self.config.base_url}{text}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query, doseq=True)}"
        return url

    def _custom_headers(
        self,
        headers: Mapping[str, Any] | None,
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for name, value in dict(headers or {}).items():
            key = str(name).strip()
            text = str(value)
            if (
                not HEADER_NAME.fullmatch(key)
                or key.lower() in BLOCKED_HEADERS
                or "\r" in text
                or "\n" in text
            ):
                raise StarIntelError(f"header is not allowed: {key!r}")
            result[key] = text
        return result

    def _request_headers(
        self,
        path: str,
        body: bytes | None,
        headers: Mapping[str, Any] | None,
    ) -> dict[str, str]:
        result = {
            "Accept": "application/json",
            "User-Agent": "Zara-StarIntel-Server/0.1.0",
            "X-Request-Timeout-Ms": str(
                max(1, int(self.config.timeout_seconds * 1000))
            ),
        }
        if body is not None:
            result["Content-Type"] = "application/json"
        if self.config.api_key:
            result["Authorization"] = f"Bearer {self.config.api_key}"
        if path == "/auth/bootstrap" and self.config.bootstrap_secret:
            result["X-Star-Bootstrap-Secret"] = self.config.bootstrap_secret
        result.update(self._custom_headers(headers))
        return result

    def _encode_body(self, body: Any) -> bytes | None:
        if body is None:
            return None
        try:
            data = json.dumps(
                body,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise StarIntelError("request body is not valid JSON data") from error
        if len(data) > self.config.max_request_bytes:
            raise StarIntelError("StarIntel request body exceeded configured limit")
        return data

    def _response_headers(self, response: Any) -> dict[str, str]:
        source = getattr(response, "headers", None)
        if source is None:
            return {}
        items = source.items() if hasattr(source, "items") else ()
        return {
            str(name).lower(): str(value)
            for name, value in items
            if str(name).lower() in SAFE_RESPONSE_HEADERS
        }

    def _decode_response(self, response: Any, status: int) -> dict[str, Any]:
        data = response.read(self.config.max_response_bytes + 1)
        if len(data) > self.config.max_response_bytes:
            raise StarIntelError("StarIntel response exceeded configured limit")
        headers = self._response_headers(response)
        text = data.decode("utf-8", errors="replace")
        decoded: Any = None
        if text:
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError:
                decoded = None
        result: dict[str, Any] = {
            "status": status,
            "ok": 200 <= status < 300,
            "headers": headers,
        }
        if decoded is not None:
            result["data"] = decoded
        elif text:
            result["body"] = text
        else:
            result["data"] = None
        correlation_id = headers.get("x-correlation-id")
        if correlation_id:
            result["correlation_id"] = correlation_id
        return result

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Any = None,
        headers: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_ready()
        normalized_method = str(method).strip().upper()
        if normalized_method not in ALLOWED_METHODS:
            raise StarIntelError(
                f"HTTP method is not supported: {normalized_method or '<empty>'}"
            )
        url = self._request_url(path, query)
        body_data = self._encode_body(body)
        request = urllib.request.Request(
            url,
            data=body_data,
            headers=self._request_headers(path, body_data, headers),
            method=normalized_method,
        )
        try:
            response = self._opener(
                request,
                timeout=self.config.timeout_seconds,
            )
            with response:
                status = int(
                    getattr(
                        response,
                        "status",
                        getattr(response, "code", 200),
                    )
                )
                return self._decode_response(response, status)
        except urllib.error.HTTPError as error:
            try:
                return self._decode_response(error, int(error.code))
            finally:
                error.close()
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise StarIntelError(f"StarIntel request failed: {error}") from error

    def capabilities(self) -> dict[str, Any]:
        result = self.request("GET", "/api/v1/capabilities")
        document = result.get("data")
        data = document.get("data") if isinstance(document, dict) else None
        endpoints = data.get("endpoints") if isinstance(data, dict) else None
        if not isinstance(endpoints, list):
            raise StarIntelError(
                "StarIntel capabilities response did not advertise endpoints"
            )
        return data

    def manifest(self, *, refresh: bool = False) -> dict[str, Any]:
        if self._manifest_cache is not None and not refresh:
            return self._manifest_cache
        result = self.request("GET", "/client-manifest.json")
        manifest = result.get("data")
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema") != "starintel-client-manifest-v1"
            or not isinstance(manifest.get("operations"), list)
        ):
            raise StarIntelError("StarIntel returned an invalid client manifest")
        self._manifest_cache = manifest
        return manifest

    def operations(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        operations = self.manifest(refresh=refresh)["operations"]
        return [dict(operation) for operation in operations]

    def _operation(self, operation_id: str) -> dict[str, Any]:
        for operation in self.operations():
            if operation.get("operation_id") == operation_id:
                return operation
        raise StarIntelError(f"unknown operation: {operation_id}")

    def _operation_path(
        self,
        operation: Mapping[str, Any],
        path_parameters: Mapping[str, Any] | None,
    ) -> str:
        path = str(operation.get("path", ""))
        provided = dict(path_parameters or {})
        expected = operation.get("path_parameters") or []
        for name in expected:
            if name not in provided:
                raise StarIntelError(f"missing path parameter: {name}")
            value = urllib.parse.quote(str(provided.pop(name)), safe="")
            path = re.sub(
                rf":{re.escape(str(name))}(?=/|$)",
                lambda _: value,
                path,
            )
        if provided:
            names = ", ".join(sorted(str(name) for name in provided))
            raise StarIntelError(f"unknown path parameters: {names}")
        if re.search(r":[A-Za-z0-9_-]+(?=/|$)", path):
            raise StarIntelError("operation path contains unresolved parameters")
        return path

    def call_operation(
        self,
        operation_id: str,
        *,
        path_parameters: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        body: Any = None,
        headers: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        operation = self._operation(str(operation_id).strip())
        method = operation.get("method")
        if not isinstance(method, str):
            raise StarIntelError("operation manifest method is invalid")
        path = self._operation_path(operation, path_parameters)
        return self.request(
            method,
            path,
            query=query,
            body=body,
            headers=headers,
        )
