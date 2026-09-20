from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from typing import Any

from zara.plugins import PluginMetadata, ServicePlugin

PLUGIN_VERSION = "0.1.0"
PROTOCOL = "ZARA-EXPERT/1"
EXPERT_ID = 'zara:expert/javascript'
PACKAGE_NAMESPACE = 'zara-javascript-expert'
EXPERT_NAME = 'JavaScriptExpert'
SOURCE_REFERENCE = 'source:dotfiles.javascript-expert'
UPSTREAM_CONTRACT = 'lost-rob0t/prolog-rlm#500'
HOST_CAPABILITY = "expert.invoke"
MAX_INPUT_BYTES = 8192
MAX_OUTPUT_BYTES = 65536
MAX_TIMEOUT_MS = 3000
MAX_RESULTS = 32
MAX_INPUT_DEPTH = 8
MAX_INPUT_KEYS = 32
MAX_INPUT_LIST = 64
MAX_STRING_LENGTH = 4096
MAX_GENERATION = 2_147_483_647
REQUEST_ID_RE = re.compile(r"^[!-~]{1,128}$")
ACTIVATION_ID_RE = re.compile(r"^act:[a-f0-9]{32}$")
RESULT_VERDICTS = frozenset({"succeeded", "failed", "unknown", "blocked", "unsupported", "cancelled", "error"})
OPERATION_FIELDS: dict[str, tuple[dict[str, object], ...]] = {
    'applicable': (
        {"name": 'source', "type": 'string', "required": False},
        {"name": 'path', "type": 'string', "required": False},
        {"name": 'project_metadata', "type": 'object', "required": False},
    ),
    'parse': (
        {"name": 'source', "type": 'string', "required": True},
        {"name": 'path', "type": 'string', "required": False},
        {"name": 'language_variant', "type": 'string', "required": False},
    ),
    'inspect_module': (
        {"name": 'source', "type": 'string', "required": True},
        {"name": 'path', "type": 'string', "required": False},
        {"name": 'project_metadata', "type": 'object', "required": False},
    ),
    'inspect_jsx': (
        {"name": 'source', "type": 'string', "required": True},
        {"name": 'path', "type": 'string', "required": False},
    ),
    'diagnose': (
        {"name": 'source', "type": 'string', "required": True},
        {"name": 'path', "type": 'string', "required": False},
        {"name": 'project_metadata', "type": 'object', "required": False},
    ),
    'style': (
        {"name": 'source', "type": 'string', "required": True},
        {"name": 'path', "type": 'string', "required": False},
        {"name": 'style_profile', "type": 'string', "required": False},
    ),
    'repair_verify': (
        {"name": 'source', "type": 'string', "required": True},
        {"name": 'candidate_source', "type": 'string', "required": True},
        {"name": 'path', "type": 'string', "required": False},
    ),
    'explain': (
        {"name": 'subject', "type": 'object', "required": True},
    ),
}
ALLOWED_OPERATIONS = frozenset(OPERATION_FIELDS)

class JavaScriptExpertAdapterError(RuntimeError):
    """Fail closed: this adapter never falls back to a provider or model."""


def _manifest_digest() -> str:
    manifest = {
        "expert_id": EXPERT_ID,
        "package_namespace": PACKAGE_NAMESPACE,
        "source_reference": SOURCE_REFERENCE,
        "upstream_contract": UPSTREAM_CONTRACT,
        "operations": {key: list(value) for key, value in sorted(OPERATION_FIELDS.items())},
    }
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()

MANIFEST_DIGEST = _manifest_digest()


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _validate_json_tree(value: object, *, depth: int = 0) -> None:
    if depth > MAX_INPUT_DEPTH:
        raise JavaScriptExpertAdapterError("input-structure-too-complex")
    if isinstance(value, dict):
        if len(value) > MAX_INPUT_KEYS:
            raise JavaScriptExpertAdapterError("input-object-too-large")
        for key, child in value.items():
            if not isinstance(key, str) or not key or len(key) > 64:
                raise JavaScriptExpertAdapterError("invalid-input-key")
            _validate_json_tree(child, depth=depth + 1)
        return
    if isinstance(value, list):
        if len(value) > MAX_INPUT_LIST:
            raise JavaScriptExpertAdapterError("input-array-too-large")
        for child in value:
            _validate_json_tree(child, depth=depth + 1)
        return
    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            raise JavaScriptExpertAdapterError("input-string-too-large")
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise JavaScriptExpertAdapterError("invalid-input-number")
    if value is None or isinstance(value, (bool, int, float)):
        return
    raise JavaScriptExpertAdapterError("invalid-input-value")


def _validate_generation(value: object, field: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_GENERATION:
        raise JavaScriptExpertAdapterError(f"invalid-{field}")
    return value


def _validate_request_id(value: object) -> str:
    if not isinstance(value, str) or REQUEST_ID_RE.fullmatch(value) is None:
        raise JavaScriptExpertAdapterError("invalid-request-id")
    return value


def _validate_activation_id(value: object) -> str:
    if not isinstance(value, str) or ACTIVATION_ID_RE.fullmatch(value) is None:
        raise JavaScriptExpertAdapterError("invalid-activation-id")
    return value


def _check_field(field: Mapping[str, object], value: object) -> None:
    kind = field["type"]
    if kind == "string" and not isinstance(value, str):
        raise JavaScriptExpertAdapterError("invalid-operation-input")
    if kind == "object" and not isinstance(value, dict):
        raise JavaScriptExpertAdapterError("invalid-operation-input")


def _validate_operation_input(operation: str, payload: Mapping[str, object]) -> None:
    fields = OPERATION_FIELDS[operation]
    declared = {field["name"]: field for field in fields}
    if set(payload) - set(declared):
        raise JavaScriptExpertAdapterError("unknown-operation-input")
    for name, field in declared.items():
        if field["required"] and name not in payload:
            raise JavaScriptExpertAdapterError("missing-operation-input")
        if name in payload:
            _check_field(field, payload[name])


def _operation_descriptor(operation: str) -> dict[str, object]:
    return {
        "operation_id": operation,
        "input_schema": {"fields": [dict(field) for field in OPERATION_FIELDS[operation]]},
        "output_schema": {"fields": []},
    }


def _validate_result(result: Mapping[str, object], *, request_id: str, activation_id: str, expert_operation: str, registry_generation: int, runtime_generation: int) -> None:
    expected = {
        "protocol": PROTOCOL,
        "request_id": request_id,
        "activation_id": activation_id,
        "expert_id": EXPERT_ID,
        "expert_version": PLUGIN_VERSION,
        "manifest_digest": MANIFEST_DIGEST,
        "expert_operation": expert_operation,
    }
    for key, value in expected.items():
        if result.get(key) != value:
            raise JavaScriptExpertAdapterError("expert-result-identity-mismatch")
    if result.get("resolved_registry_generation") != registry_generation or result.get("resolved_runtime_generation") != runtime_generation:
        raise JavaScriptExpertAdapterError("stale-expert-result")
    if result.get("verdict") not in RESULT_VERDICTS:
        raise JavaScriptExpertAdapterError("invalid-expert-verdict")
    usage = result.get("usage")
    model_calls = usage.get("model_calls") if isinstance(usage, Mapping) else None
    if type(model_calls) is not int or model_calls != 0:
        raise JavaScriptExpertAdapterError("zero-model-proof-missing")
    receipts = result.get("effect_receipts")
    if not isinstance(receipts, (list, tuple)):
        raise JavaScriptExpertAdapterError("read-only-effect-proof-missing")
    if receipts:
        raise JavaScriptExpertAdapterError("read-only-effect-leak")


class ZaraJavaScriptExpertPlugin(ServicePlugin):
    metadata = PluginMetadata(name=PACKAGE_NAMESPACE, version=PLUGIN_VERSION, api_version="1", description='Deterministic JavaScript and JSX syntax, module, diagnostic, style, and repair-verification adapter.')

    def __init__(self) -> None:
        self._runtime: Any | None = None

    def start(self, runtime: Any) -> None:
        # Passive bind only. Discovery must not activate an expert or touch a provider/network/process.
        self._runtime = runtime

    def stop(self) -> None:
        self._runtime = None

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _decode_input(input_json: str) -> dict[str, Any]:
        if not isinstance(input_json, str):
            raise JavaScriptExpertAdapterError("input-must-be-json-text")
        if len(input_json.encode()) > MAX_INPUT_BYTES:
            raise JavaScriptExpertAdapterError("input-too-large")
        try:
            value = json.loads(input_json, parse_constant=_reject_json_constant)
        except (TypeError, ValueError) as error:
            raise JavaScriptExpertAdapterError("invalid-input-json") from error
        if not isinstance(value, dict):
            raise JavaScriptExpertAdapterError("input-must-be-object")
        _validate_json_tree(value)
        return value

    def descriptor(self) -> str:
        return self._json({
            "protocol": PROTOCOL,
            "expert_id": EXPERT_ID,
            "expert_version": PLUGIN_VERSION,
            "package_namespace": PACKAGE_NAMESPACE,
            "manifest_digest": MANIFEST_DIGEST,
            "name": EXPERT_NAME,
            "description": 'Deterministic JavaScript and JSX syntax, module, diagnostic, style, and repair-verification adapter.',
            "source_reference": SOURCE_REFERENCE,
            "reasoning_kind": "symbolic",
            "operations": [_operation_descriptor(operation) for operation in sorted(ALLOWED_OPERATIONS)],
            "applicability": {"keywords": ['javascript', 'js', 'jsx', 'ecmascript', 'esm', 'commonjs']},
            "required_capabilities": [HOST_CAPABILITY],
            "possible_effects": ["none"],
            "supported_engines": ["swipl"],
            "supported_platforms": ['desktop', 'server', 'android'],
            "fallback_policy": "fail_closed",
            "delegation_policy": "never",
            "resource_limits": {"timeout_ms": MAX_TIMEOUT_MS, "max_results": MAX_RESULTS, "max_output_bytes": MAX_OUTPUT_BYTES, "max_model_calls": 0},
            "registry_generation": 1,
            "availability": "unavailable",
            "unavailable_reason": "canonical-source-or-host-not-activated",
        })

    def invoke(self, request_id: str, activation_id: str, expert_operation: str, expected_registry_generation: int, expected_runtime_generation: int, input_json: str = "{}") -> str:
        if expert_operation not in ALLOWED_OPERATIONS:
            raise JavaScriptExpertAdapterError("unsupported-expert-operation")
        request_id = _validate_request_id(request_id)
        activation_id = _validate_activation_id(activation_id)
        registry_generation = _validate_generation(expected_registry_generation, "registry-generation")
        runtime_generation = _validate_generation(expected_runtime_generation, "runtime-generation")
        payload = self._decode_input(input_json)
        _validate_operation_input(expert_operation, payload)
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
            "expected_registry_generation": registry_generation,
            "expected_runtime_generation": runtime_generation,
            "input": payload,
            "limits": {"timeout_ms": MAX_TIMEOUT_MS, "max_results": MAX_RESULTS, "max_output_bytes": MAX_OUTPUT_BYTES, "max_model_calls": 0},
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
        _validate_result(result, request_id=request_id, activation_id=activation_id, expert_operation=expert_operation, registry_generation=registry_generation, runtime_generation=runtime_generation)
        encoded = self._json(dict(result))
        if len(encoded.encode()) > MAX_OUTPUT_BYTES:
            raise JavaScriptExpertAdapterError("expert-result-too-large")
        return encoded

    def tools(self):
        # ZARA-EXPERT/1 activation/invocation is owned by Zara Core. Do not expose
        # an adapter-local StructuredTool surface that could bypass that authority.
        return ()


def create_plugin():
    return ZaraJavaScriptExpertPlugin()
