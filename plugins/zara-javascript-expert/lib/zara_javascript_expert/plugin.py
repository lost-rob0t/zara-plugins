from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin


PLUGIN_VERSION = "0.1.0"
PROTOCOL = "ZARA-EXPERT/1"
EXPERT_ID = 'language:javascript'
PACKAGE_NAMESPACE = 'zara-javascript-expert'
EXPERT_NAME = 'JavaScriptExpert'
SOURCE_REFERENCE = 'source:dotfiles.javascript-expert'
UPSTREAM_CONTRACT = 'lost-rob0t/prolog-rlm#500'
HOST_CAPABILITY = "expert.invoke"
INPUT_SCHEMA = "schema:zara.language-expert.subject.v1"
OUTPUT_SCHEMA = "schema:zara.language-expert.result.v1"
MAX_INPUT_BYTES = 65536
MAX_OUTPUT_BYTES = 65536
MAX_RESULTS = 16
TIMEOUT_MS = 1000
_REFERENCE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
ALLOWED_OPERATIONS = ('applicable', 'parse', 'inspect', 'inspect_module', 'inspect_jsx', 'diagnose', 'style', 'repair_verify', 'explain')
REQUIRED_OBSERVATIONS = ('source-index', 'ecmascript-project-metadata')


class JavaScriptExpertAdapterError(RuntimeError):
    """Fail-closed pure-symbolic adapter error."""


def _manifest_digest() -> str:
    manifest = {
        "expert_id": EXPERT_ID,
        "package_namespace": PACKAGE_NAMESPACE,
        "source_reference": SOURCE_REFERENCE,
        "upstream_contract": UPSTREAM_CONTRACT,
        "operations": list(ALLOWED_OPERATIONS),
        "required_observations": list(REQUIRED_OBSERVATIONS),
    }
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_reference(value: object, field: str) -> str:
    if not isinstance(value, str) or not _REFERENCE_RE.fullmatch(value):
        raise JavaScriptExpertAdapterError(f"invalid-{field}")
    return value


def _validate_generation(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise JavaScriptExpertAdapterError(f"invalid-{field}")
    return value


def _validate_json_tree(value: object, *, depth: int = 0, budget: list[int] | None = None) -> None:
    if budget is None:
        budget = [4096]
    budget[0] -= 1
    if budget[0] < 0 or depth > 16:
        raise JavaScriptExpertAdapterError("input-structure-too-large")
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        if len(value) > 4096:
            raise JavaScriptExpertAdapterError("input-string-too-large")
        return
    if isinstance(value, list):
        if len(value) > 256:
            raise JavaScriptExpertAdapterError("input-array-too-large")
        for item in value:
            _validate_json_tree(item, depth=depth + 1, budget=budget)
        return
    if isinstance(value, dict):
        if len(value) > 128:
            raise JavaScriptExpertAdapterError("input-object-too-large")
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 128:
                raise JavaScriptExpertAdapterError("invalid-input-key")
            _validate_json_tree(item, depth=depth + 1, budget=budget)
        return
    raise JavaScriptExpertAdapterError("input-not-json-compatible")


class ZaraJavaScriptExpertPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name=PACKAGE_NAMESPACE,
        version=PLUGIN_VERSION,
        api_version="1",
        description='Deterministic JavaScript/JSX syntax, module, diagnostic, style, and repair-verification adapter.',
    )

    def __init__(self) -> None:
        self._runtime: Any | None = None

    def start(self, runtime: Any) -> None:
        # Passive bind only: no activation, provider, network, parser/compiler,
        # subprocess, expert query, or model call occurs during discovery.
        self._runtime = runtime
        return None

    def stop(self) -> None:
        self._runtime = None

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _decode_input(input_json: str) -> dict[str, Any]:
        if not isinstance(input_json, str):
            raise JavaScriptExpertAdapterError("input-must-be-json-text")
        if len(input_json.encode("utf-8")) > MAX_INPUT_BYTES:
            raise JavaScriptExpertAdapterError("input-too-large")
        try:
            payload = json.loads(input_json)
        except (TypeError, ValueError) as error:
            raise JavaScriptExpertAdapterError("invalid-input-json") from error
        if not isinstance(payload, dict):
            raise JavaScriptExpertAdapterError("input-must-be-object")
        _validate_json_tree(payload)
        return payload

    def descriptor(self) -> str:
        runtime = self._runtime
        node_id = getattr(runtime, "node_id", "node.local") if runtime is not None else "node.local"
        runtime_id = getattr(runtime, "runtime_id", "zara-runtime") if runtime is not None else "zara-runtime"
        registry_generation = getattr(runtime, "registry_generation", 1) if runtime is not None else 1
        node_id = _validate_reference(node_id, "node-id")
        if not isinstance(runtime_id, str) or not _TOKEN_RE.fullmatch(runtime_id):
            raise JavaScriptExpertAdapterError("invalid-runtime-id")
        registry_generation = _validate_generation(registry_generation, "registry-generation")
        operations = [
            {
                "id": operation,
                "input_schema": INPUT_SCHEMA,
                "output_schema": OUTPUT_SCHEMA,
                "effects": [],
                "required_capabilities": [HOST_CAPABILITY],
            }
            for operation in ALLOWED_OPERATIONS
        ]
        return self._json(
            {
                "protocol": PROTOCOL,
                "expert_id": EXPERT_ID,
                "expert_version": PLUGIN_VERSION,
                "package_namespace": PACKAGE_NAMESPACE,
                "manifest_digest": _manifest_digest(),
                "name": EXPERT_NAME,
                "description": 'Deterministic JavaScript/JSX syntax, module, diagnostic, style, and repair-verification adapter.',
                "source_reference": SOURCE_REFERENCE,
                "reasoning_kind": "symbolic",
                "operations": operations,
                "applicability_schema": INPUT_SCHEMA,
                "required_observations": list(REQUIRED_OBSERVATIONS),
                "required_capabilities": [HOST_CAPABILITY],
                "possible_effects": [],
                "supported_engines": ["swipl"],
                "supported_platforms": ["zara-runtime"],
                "placement": {"node_id": node_id, "runtime_id": runtime_id},
                "fallback_policy": "none",
                "delegation_policy": "none",
                "resource_limits": {
                    "timeout_ms": TIMEOUT_MS,
                    "max_results": MAX_RESULTS,
                    "max_output_bytes": MAX_OUTPUT_BYTES,
                    "max_model_calls": 0,
                },
                "registry_generation": registry_generation,
                "availability": "unavailable",
                "unavailable_reason": "activation-required",
            }
        )

    def invoke(
        self,
        request_id: str,
        activation_id: str,
        expert_operation: str,
        expected_registry_generation: int,
        expected_runtime_generation: int,
        input_json: str = "{}",
    ) -> str:
        request_id = _validate_reference(request_id, "request-id")
        activation_id = _validate_reference(activation_id, "activation-id")
        expected_registry_generation = _validate_generation(
            expected_registry_generation, "registry-generation"
        )
        expected_runtime_generation = _validate_generation(
            expected_runtime_generation, "runtime-generation"
        )
        if expert_operation not in ALLOWED_OPERATIONS:
            raise JavaScriptExpertAdapterError("unsupported-expert-operation")
        payload = self._decode_input(input_json)

        runtime = self._runtime
        resolver = getattr(runtime, "resolve_capability", None)
        invoker = getattr(runtime, "invoke_capability", None)
        if not callable(resolver) or not callable(invoker):
            raise JavaScriptExpertAdapterError("expert-host-composition-unavailable")

        request = {
            "protocol": PROTOCOL,
            "request_id": request_id,
            "operation": "expert.invoke",
            "activation_id": activation_id,
            "expert_id": EXPERT_ID,
            "expert_operation": expert_operation,
            "expected_registry_generation": expected_registry_generation,
            "expected_runtime_generation": expected_runtime_generation,
            "input": payload,
            "limits": {
                "timeout_ms": TIMEOUT_MS,
                "max_results": MAX_RESULTS,
                "max_output_bytes": MAX_OUTPUT_BYTES,
                "max_model_calls": 0,
            },
        }
        try:
            handle = resolver(HOST_CAPABILITY)
            result = invoker(handle, request)
        except JavaScriptExpertAdapterError:
            raise
        except Exception as error:
            raise JavaScriptExpertAdapterError("expert-host-invocation-failed") from error

        if not isinstance(result, Mapping):
            raise JavaScriptExpertAdapterError("invalid-expert-result")
        usage = result.get("usage")
        model_calls = usage.get("model_calls") if isinstance(usage, Mapping) else None
        if type(model_calls) is not int or model_calls != 0:
            raise JavaScriptExpertAdapterError("zero-model-proof-missing")
        if result.get("request_id") != request_id:
            raise JavaScriptExpertAdapterError("stale-or-unbound-expert-result")
        if result.get("registry_generation") != expected_registry_generation:
            raise JavaScriptExpertAdapterError("stale-or-unbound-expert-result")
        if result.get("runtime_generation") != expected_runtime_generation:
            raise JavaScriptExpertAdapterError("stale-or-unbound-expert-result")
        evidence = result.get("evidence")
        explanation = result.get("explanation")
        if not isinstance(evidence, list) or not isinstance(explanation, list):
            raise JavaScriptExpertAdapterError("evidence-or-explanation-missing")
        receipts = result.get("side_effect_receipts")
        if not isinstance(receipts, list) or receipts:
            raise JavaScriptExpertAdapterError("unexpected-side-effect-receipt")

        encoded = self._json(dict(result))
        if len(encoded.encode("utf-8")) > MAX_OUTPUT_BYTES:
            raise JavaScriptExpertAdapterError("expert-result-too-large")
        return encoded

    def tools(self):
        prefix = EXPERT_ID.split(":", 1)[1]
        return (
            StructuredTool.from_function(
                func=self.descriptor,
                name=f"{prefix}.expert.descriptor",
                description=f"Return the passive {EXPERT_NAME} ZARA-EXPERT/1 descriptor.",
            ),
            StructuredTool.from_function(
                func=self.invoke,
                name=f"{prefix}.expert.invoke",
                description=(
                    f"Invoke one allowlisted pure-symbolic {EXPERT_NAME} operation through "
                    "the canonical expert.invoke capability with explicit generation fences."
                ),
            ),
        )


def create_plugin():
    return ZaraJavaScriptExpertPlugin()
