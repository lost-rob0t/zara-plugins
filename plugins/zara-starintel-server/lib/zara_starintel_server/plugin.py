"""Zara service plugin exposing StarIntel Server and the StarKB service expert."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .client import StarIntelClient, StarIntelError
from .config import StarIntelConfig
from .star_kb import EXPERT_ID, SOURCE_REFERENCE, StarKB, descriptor as star_kb_descriptor


PLUGIN_VERSION = "0.2.0"


def _json_value(value: str, label: str, default: Any) -> Any:
    text = str(value).strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise StarIntelError(f"{label} must be valid JSON") from error


def _json_mapping(value: str, label: str) -> dict[str, Any]:
    decoded = _json_value(value, label, {})
    if not isinstance(decoded, dict):
        raise StarIntelError(f"{label} must be a JSON object")
    return decoded


class ZaraStarIntelServerPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-starintel-server",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Agentic StarKB expert plus bounded live StarIntel Server API access",
    )

    def __init__(self) -> None:
        self._config = StarIntelConfig()
        self._client = StarIntelClient(self._config)
        self._star_kb = StarKB(self._client, self._config)
        self._expert_published = False

    def start(self, runtime) -> None:
        self._config = StarIntelConfig.load(runtime.configuration)
        self._client = StarIntelClient(self._config)
        self._star_kb = StarKB(self._client, self._config)
        self._expert_published = False

        registrar = getattr(runtime, "register_symbol", None)
        if callable(registrar):
            item = star_kb_descriptor(available=self._star_kb.available)
            registrar(
                EXPERT_ID,
                "expert",
                item,
                docs=item["description"],
                capabilities=("star-kb.run",),
                source=SOURCE_REFERENCE,
            )
            self._expert_published = True

    def stop(self) -> None:
        self._expert_published = False
        return None

    def tools(self):
        return (
            StructuredTool.from_function(
                func=self.star_kb_descriptor,
                name="star-kb.descriptor",
                description=(
                    "Return the ZARA-EXPERT/1 descriptor for the StarKB StarIntel "
                    "service expert, including availability, operations and limits."
                ),
            ),
            StructuredTool.from_function(
                func=self.star_kb_observe,
                name="star-kb.observe",
                description=(
                    "Observe live StarIntel capabilities and operation discovery for "
                    "agent planning. This performs no write operation."
                ),
            ),
            StructuredTool.from_function(
                func=self.star_kb_plan,
                name="star-kb.plan",
                description=(
                    "Build a bounded StarKB plan by ranking the live StarIntel client "
                    "manifest against a goal. Write-capable operations are excluded "
                    "unless explicitly admitted."
                ),
            ),
            StructuredTool.from_function(
                func=self.star_kb_run,
                name="star-kb.run",
                description=(
                    "Run a bounded StarKB plan over live StarIntel operations. It is "
                    "dry-run by default; writes require allow_writes=true and, by "
                    "default, an Idempotency-Key binding."
                ),
            ),
            StructuredTool.from_function(
                func=self.star_kb_explain,
                name="star-kb.explain",
                description=(
                    "Explain StarKB's read-only live-manifest operation selection for "
                    "a StarIntel goal."
                ),
            ),
            StructuredTool.from_function(
                func=self.starintel_status,
                name="starintel_status",
                description=(
                    "Show StarIntel Server plugin configuration state and optionally "
                    "check the remote /health endpoint. Secrets are never returned."
                ),
            ),
            StructuredTool.from_function(
                func=self.starintel_capabilities,
                name="starintel_capabilities",
                description=(
                    "Fetch StarIntel Server capabilities, features, limits, scopes, "
                    "and advertised endpoints."
                ),
            ),
            StructuredTool.from_function(
                func=self.starintel_api_operations,
                name="starintel_api_operations",
                description=(
                    "List every operation in the live StarIntel client manifest, "
                    "including methods, paths, authority, scopes, schemas, and responses."
                ),
            ),
            StructuredTool.from_function(
                func=self.starintel_call_operation,
                name="starintel_call_operation",
                description=(
                    "Call a named operation from the live StarIntel client manifest. "
                    "Supports reads, writes, authentication, credential administration, "
                    "user administration, documents, targets, and future contracted APIs."
                ),
            ),
            StructuredTool.from_function(
                func=self.starintel_api_request,
                name="starintel_api_request",
                description=(
                    "Send a bounded same-origin GET, POST, PUT, PATCH, or DELETE request "
                    "to any StarIntel API path with JSON, form, or text bodies, including "
                    "legacy and newly deployed routes. This can perform destructive or "
                    "administrative operations."
                ),
            ),
        )

    def star_kb_descriptor(self) -> str:
        return json.dumps(
            star_kb_descriptor(available=self._star_kb.available),
            ensure_ascii=False,
            sort_keys=True,
        )

    def star_kb_observe(self, refresh: bool = False) -> str:
        return json.dumps(
            self._star_kb.observe(refresh=refresh),
            ensure_ascii=False,
            sort_keys=True,
        )

    def star_kb_plan(
        self,
        goal: str,
        max_steps: int = 4,
        allow_writes: bool = False,
        refresh: bool = False,
    ) -> str:
        return json.dumps(
            self._star_kb.plan(
                goal,
                max_steps=max_steps,
                allow_writes=allow_writes,
                refresh=refresh,
            ),
            ensure_ascii=False,
            sort_keys=True,
        )

    def star_kb_run(
        self,
        goal: str,
        bindings_json: str = "{}",
        max_steps: int = 4,
        allow_writes: bool = False,
        dry_run: bool = True,
        require_idempotency: bool = True,
    ) -> str:
        return json.dumps(
            self._star_kb.run(
                goal,
                bindings=_json_mapping(bindings_json, "bindings_json"),
                max_steps=max_steps,
                allow_writes=allow_writes,
                dry_run=dry_run,
                require_idempotency=require_idempotency,
            ),
            ensure_ascii=False,
            sort_keys=True,
        )

    def star_kb_explain(self, goal: str, max_steps: int = 4) -> str:
        return json.dumps(
            self._star_kb.explain(goal, max_steps=max_steps),
            ensure_ascii=False,
            sort_keys=True,
        )

    def starintel_status(self, include_health: bool = True) -> str:
        status: dict[str, Any] = {
            "enabled": self._config.enabled,
            "configured": bool(self._config.base_url),
            "base_url": self._config.base_url,
            "api_key_configured": bool(self._config.api_key),
            "bootstrap_secret_configured": bool(
                self._config.bootstrap_secret
            ),
            "allow_insecure_http": self._config.allow_insecure_http,
            "timeout_seconds": self._config.timeout_seconds,
            "max_request_bytes": self._config.max_request_bytes,
            "max_response_bytes": self._config.max_response_bytes,
            "star_kb": {
                "expert_id": EXPERT_ID,
                "available": self._star_kb.available,
                "published": self._expert_published,
            },
        }
        if (
            include_health
            and self._config.enabled
            and self._config.base_url
        ):
            status["health"] = self._client.request("GET", "/health")
        return json.dumps(status, ensure_ascii=False, sort_keys=True)

    def starintel_capabilities(self) -> str:
        return json.dumps(
            self._client.capabilities(),
            ensure_ascii=False,
            sort_keys=True,
        )

    def starintel_api_operations(self, refresh: bool = False) -> str:
        return json.dumps(
            self._client.operations(refresh=refresh),
            ensure_ascii=False,
            sort_keys=True,
        )

    def starintel_call_operation(
        self,
        operation_id: str,
        path_parameters_json: str = "{}",
        query_json: str = "{}",
        body_json: str = "",
        headers_json: str = "{}",
    ) -> str:
        result = self._client.call_operation(
            operation_id,
            path_parameters=_json_mapping(
                path_parameters_json,
                "path_parameters_json",
            ),
            query=_json_mapping(query_json, "query_json"),
            body=_json_value(body_json, "body_json", None),
            headers=_json_mapping(headers_json, "headers_json"),
        )
        return json.dumps(result, ensure_ascii=False, sort_keys=True)

    def starintel_api_request(
        self,
        method: str,
        path: str,
        query_json: str = "{}",
        body_json: str = "",
        body_format: str = "json",
        headers_json: str = "{}",
    ) -> str:
        result = self._client.request(
            method,
            path,
            query=_json_mapping(query_json, "query_json"),
            body=_json_value(body_json, "body_json", None),
            body_format=body_format,
            headers=_json_mapping(headers_json, "headers_json"),
        )
        return json.dumps(result, ensure_ascii=False, sort_keys=True)


def create_plugin():
    return ZaraStarIntelServerPlugin()
