"""Bounded Agent Zero native API HTTP client."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable

from .config import AgentZeroConfig


class AgentZeroBridgeError(RuntimeError):
    pass


class AgentZeroClient:
    def __init__(
        self,
        config: AgentZeroConfig,
        *,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.config = config
        self._opener = opener

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.config.enabled:
            raise AgentZeroBridgeError("Agent Zero bridge is disabled")
        if not self.config.base_url:
            raise AgentZeroBridgeError("Agent Zero base_url is not configured")
        if not self.config.api_key:
            raise AgentZeroBridgeError("Agent Zero api_key is not configured")

        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-API-KEY": self.config.api_key,
        }
        request = urllib.request.Request(
            f"{self.config.base_url}{path}",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            response = self._opener(request, timeout=self.config.timeout_seconds)
            with response:
                data = response.read(self.config.max_response_bytes + 1)
        except urllib.error.HTTPError as error:
            detail = error.read(min(self.config.max_response_bytes, 4096)).decode(
                "utf-8", errors="replace"
            )
            detail = " ".join(detail.split())[:512]
            raise AgentZeroBridgeError(
                f"Agent Zero HTTP {error.code}: {detail or error.reason}"
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise AgentZeroBridgeError(f"Agent Zero request failed: {error}") from error

        if len(data) > self.config.max_response_bytes:
            raise AgentZeroBridgeError("Agent Zero response exceeded configured limit")
        try:
            decoded = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AgentZeroBridgeError("Agent Zero returned invalid JSON") from error
        if not isinstance(decoded, dict):
            raise AgentZeroBridgeError("Agent Zero returned a non-object response")
        if "error" in decoded:
            raise AgentZeroBridgeError(f"Agent Zero error: {str(decoded['error'])[:512]}")
        return decoded

    def status(self) -> dict[str, Any]:
        return {
            "api": "agent-zero-native",
            "endpoint": "/api/api_message",
            "enabled": self.config.enabled,
            "configured": bool(
                self.config.enabled and self.config.base_url and self.config.api_key
            ),
            "base_url": self.config.base_url,
            "api_key_configured": bool(self.config.api_key),
        }

    def send_message(
        self,
        message: str,
        *,
        context_id: str = "",
        project_name: str = "",
        agent_profile: str = "",
        lifetime_hours: float = 24.0,
    ) -> dict[str, Any]:
        text = str(message).strip()
        if not text:
            raise AgentZeroBridgeError("message is required")
        if len(text) > self.config.max_message_chars:
            raise AgentZeroBridgeError("message exceeds configured limit")
        try:
            lifetime = float(lifetime_hours)
        except (TypeError, ValueError) as error:
            raise AgentZeroBridgeError("lifetime_hours must be a positive number") from error
        if lifetime <= 0:
            raise AgentZeroBridgeError("lifetime_hours must be a positive number")

        payload: dict[str, Any] = {
            "message": text,
            "lifetime_hours": lifetime,
        }
        if context_id.strip():
            payload["context_id"] = context_id.strip()
        if project_name.strip():
            payload["project_name"] = project_name.strip()
        if agent_profile.strip():
            payload["agent_profile"] = agent_profile.strip()
        return self._post("/api/api_message", payload)
