from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from typing import Any

from zara.plugins import PluginMetadata, ServicePlugin

PLUGIN_VERSION = "0.1.0"
PROTOCOL = "ZARA-EXPERT/1"
EXPERT_ID = "zara:expert/python"
PACKAGE_NAMESPACE = "zara-python-expert"
EXPERT_NAME = "PythonExpert"
SOURCE_REFERENCE = "source:dotfiles.python-expert"
UPSTREAM_CONTRACT = "lost-rob0t/prolog-rlm#498"
HOST_CAPABILITY = "expert.invoke"
MANIFEST_DIGEST = "sha256:895f41c452dee5dbe561c4bb52ee92588903ef4dcfda4686a1999d67bb163e06"
MAX_INPUT_BYTES = 8192
MAX_OUTPUT_BYTES = 65536
MAX_TIMEOUT_MS = 3000
MAX_RESULTS = 32
MAX_GENERATION = 2_147_483_647
MAX_EVIDENCE_REFS = 32
MAX_STRING_LENGTH = 4096
REQUEST_ID_RE = re.compile(r"^[!-~]{1,128}$")
ACTIVATION_ID_RE = re.compile(r"^act:[a-f0-9]{32}$")
INVOCATION_ID_RE = re.compile(r"^inv:[a-f0-9]{32}$")
RESULT_VERDICTS = frozenset({"succeeded", "failed", "unknown", "blocked", "unsupported", "cancelled", "error"})
RESULT_ERROR_CODES = frozenset({
    "invalid_input",
    "ambiguity",
    "unsupported_operation",
    "unsupported_backend",
    "incompatible_protocol",
    "denied",
    "approval_required",
    "stale_generation",
    "unavailable",
    "deadline_exceeded",
    "budget_exceeded",
    "cancelled",
    "interrupted",
    "unknown_external_outcome",
})
RESULT_FIELDS = frozenset({"protocol", "request_id", "invocation_id", "activation_id", "expert_id", "expert_version", "manifest_digest", "expert_operation", "resolved_registry_generation", "resolved_runtime_generation", "verdict", "data", "evidence_refs", "usage", "effect_receipts", "error_code", "error_message", "replayed"})
USAGE_FIELDS = frozenset({"model_calls"})
OPERATION_FIELDS: dict[str, tuple[dict[str, object], ...]] = {
    "match": ({"name": "path", "type": "string", "required": True}, {"name": "source_generation", "type": "reference", "required": True}),
    "inspect": ({"name": "source", "type": "string", "required": True}, {"name": "source_generation", "type": "reference", "required": True}),
    "diagnose": ({"name": "source", "type": "string", "required": True}, {"name": "source_generation", "type": "reference", "required": True}),
    "repair.preview": ({"name": "source", "type": "string", "required": True}, {"name": "source_generation", "type": "reference", "required": True}, {"name": "diagnostic_ref", "type": "reference", "required": True}),
    "repair.verify": ({"name": "original_source", "type": "string", "required": True}, {"name": "candidate_source", "type": "string", "required": True}, {"name": "source_generation", "type": "reference", "required": True}),
    "style.rules": ({"name": "source", "type": "string", "required": True}, {"name": "project_style", "type": "reference", "required": True}),
    "explain": ({"name": "decision_ref", "type": "reference", "required": True}, {"name": "source_generation", "type": "reference", "required": True}),
}
OPERATION_OUTPUT_FIELDS: dict[str, tuple[dict[str, object], ...]] = {
    "match": ({"name": "applicable", "type": "boolean", "required": True},),
    "inspect": ({"name": "result", "type": "object", "required": True},),
    "diagnose": ({"name": "diagnostics", "type": "list", "required": True},),
    "repair.preview": ({"name": "repair", "type": "object", "required": True},),
    "repair.verify": ({"name": "verified", "type": "boolean", "required": True}, {"name": "postcondition_evidence", "type": "object", "required": True}),
    "style.rules": ({"name": "style_rules", "type": "list", "required": True}, {"name": "style_provenance", "type": "list", "required": True}),
    "explain": ({"name": "explanation", "type": "object", "required": True},),
}
ALLOWED_OPERATIONS = frozenset(OPERATION_FIELDS)
LANGUAGE_BOUNDARIES = {
    "language": "python",
    "extensions": (".py", ".pyi"),
    "applicability_keywords": ("python", "py", "pyi"),
    "evidence_topics": ("syntax", "typing", "imports", "diagnostics", "style", "repair-verification"),
}


class PythonExpertAdapterError(RuntimeError):
    """Fail closed; this adapter has no model/provider fallback."""


def _validate_generation(value: object, field: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_GENERATION:
        raise PythonExpertAdapterError(f"invalid-{field}")
    return value


def _decode_input(input_json: str, operation: str) -> dict[str, Any]:
    if type(input_json) is not str:
        raise PythonExpertAdapterError("input-must-be-json-text")
    if len(input_json.encode("utf-8")) > MAX_INPUT_BYTES:
        raise PythonExpertAdapterError("input-too-large")
    try:
        payload = json.loads(input_json, parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
    except (TypeError, ValueError) as error:
        raise PythonExpertAdapterError("invalid-input-json") from error
    if type(payload) is not dict:
        raise PythonExpertAdapterError("input-must-be-object")
    declared = {field["name"]: field for field in OPERATION_FIELDS[operation]}
    if set(payload) - set(declared):
        raise PythonExpertAdapterError("unknown-operation-input")
    for name, field in declared.items():
        if field["required"] and name not in payload:
            raise PythonExpertAdapterError("missing-operation-input")
        if name in payload and type(payload[name]) is not str:
            raise PythonExpertAdapterError("invalid-operation-input")
    return payload


def _validate_data_tree(value: object, depth: int = 0) -> None:
    if depth > 64:
        raise PythonExpertAdapterError("invalid-expert-data-json")
    if type(value) is dict:
        for key, child in value.items():
            if type(key) is not str:
                raise PythonExpertAdapterError("invalid-expert-data-json")
            _validate_data_tree(child, depth + 1)
        return
    if type(value) in (list, tuple):
        for child in value:
            _validate_data_tree(child, depth + 1)
        return
    if type(value) is float and not math.isfinite(value):
        raise PythonExpertAdapterError("invalid-expert-data-json")
    if value is None or type(value) in (str, int, bool, float):
        return
    raise PythonExpertAdapterError("invalid-expert-data-json")


def _validate_output(operation: str, verdict: str, data: object) -> None:
    if type(data) is not dict:
        raise PythonExpertAdapterError("invalid-expert-output")
    _validate_data_tree(data)
    if verdict != "succeeded":
        if data:
            raise PythonExpertAdapterError("invalid-expert-output")
        return
    declared = {field["name"]: field for field in OPERATION_OUTPUT_FIELDS[operation]}
    if set(data) - set(declared):
        raise PythonExpertAdapterError("invalid-expert-output")
    for name, field in declared.items():
        if field["required"] and name not in data:
            raise PythonExpertAdapterError("invalid-expert-output")
        if name not in data:
            continue
        value = data[name]
        kind = field["type"]
        valid = type(value) is bool if kind == "boolean" else type(value) is dict if kind == "object" else type(value) is list if kind == "list" else False
        if not valid:
            raise PythonExpertAdapterError("invalid-expert-output")


def _validate_result_metadata(result: Mapping[str, object]) -> None:
    if any(type(field) is not str or field not in RESULT_FIELDS for field in result):
        raise PythonExpertAdapterError("unknown-expert-result-field")
    error_code = result.get("error_code")
    if error_code is not None and (
        type(error_code) is not str or error_code not in RESULT_ERROR_CODES
    ):
        raise PythonExpertAdapterError("invalid-expert-error-code")
    error_message = result.get("error_message", "")
    if type(error_message) is not str or len(error_message) > MAX_STRING_LENGTH:
        raise PythonExpertAdapterError("invalid-expert-error-message")
    replayed = result.get("replayed", False)
    if type(replayed) is not bool:
        raise PythonExpertAdapterError("invalid-expert-replayed")


def _validate_result(result: Mapping[str, object], *, request_id: str, activation_id: str, operation: str, registry_generation: int, runtime_generation: int) -> None:
    _validate_result_metadata(result)
    invocation_id = result.get("invocation_id")
    if type(invocation_id) is not str or INVOCATION_ID_RE.fullmatch(invocation_id) is None:
        raise PythonExpertAdapterError("invalid-expert-invocation-id")
    expected = {"protocol": PROTOCOL, "request_id": request_id, "activation_id": activation_id, "expert_id": EXPERT_ID, "expert_version": PLUGIN_VERSION, "manifest_digest": MANIFEST_DIGEST, "expert_operation": operation}
    if any(result.get(key) != value for key, value in expected.items()):
        raise PythonExpertAdapterError("expert-result-identity-mismatch")
    if type(result.get("resolved_registry_generation")) is not int or result.get("resolved_registry_generation") != registry_generation:
        raise PythonExpertAdapterError("stale-expert-result")
    if type(result.get("resolved_runtime_generation")) is not int or result.get("resolved_runtime_generation") != runtime_generation:
        raise PythonExpertAdapterError("stale-expert-result")
    verdict = result.get("verdict")
    if type(verdict) is not str or verdict not in RESULT_VERDICTS:
        raise PythonExpertAdapterError("invalid-expert-verdict")
    usage = result.get("usage")
    if type(usage) is not dict or set(usage) != USAGE_FIELDS or type(usage.get("model_calls")) is not int or usage.get("model_calls") != 0:
        raise PythonExpertAdapterError("zero-model-proof-missing")
    receipts = result.get("effect_receipts")
    if type(receipts) not in (list, tuple):
        raise PythonExpertAdapterError("read-only-effect-proof-missing")
    if receipts:
        raise PythonExpertAdapterError("read-only-effect-leak")
    evidence = result.get("evidence_refs")
    if type(evidence) not in (list, tuple) or len(evidence) > MAX_EVIDENCE_REFS or any(type(item) is not str for item in evidence):
        raise PythonExpertAdapterError("invalid-expert-evidence")
    if verdict == "cancelled" and evidence:
        raise PythonExpertAdapterError("cancelled-expert-output-leak")
    _validate_output(operation, verdict, result.get("data"))


def _operation_descriptor(operation: str) -> dict[str, object]:
    return {"operation_id": operation, "input_schema": {"fields": [dict(field) for field in OPERATION_FIELDS[operation]]}, "output_schema": {"fields": [dict(field) for field in OPERATION_OUTPUT_FIELDS[operation]]}}


class ZaraPythonExpertPlugin(ServicePlugin):
    metadata = PluginMetadata(name=PACKAGE_NAMESPACE, version=PLUGIN_VERSION, api_version="1", description="Pure-symbolic PythonExpert adapter over the canonical Zara expert host")

    def __init__(self) -> None:
        self._runtime: Any | None = None

    def start(self, runtime: Any) -> None:
        self._runtime = runtime

    def stop(self) -> None:
        self._runtime = None

    def descriptor(self) -> str:
        return json.dumps({
            "protocol": PROTOCOL, "expert_id": EXPERT_ID, "expert_version": PLUGIN_VERSION,
            "package_namespace": PACKAGE_NAMESPACE, "manifest_digest": MANIFEST_DIGEST,
            "name": EXPERT_NAME, "description": "Pure-symbolic PythonExpert product adapter",
            "source_reference": SOURCE_REFERENCE, "reasoning_kind": "symbolic",
            "operations": [_operation_descriptor(operation) for operation in sorted(ALLOWED_OPERATIONS)],
            "applicability": {"extensions": list(LANGUAGE_BOUNDARIES["extensions"]), "keywords": list(LANGUAGE_BOUNDARIES["applicability_keywords"])},
            "required_capabilities": [HOST_CAPABILITY], "possible_effects": ["none"],
            "supported_engines": ["swipl"], "supported_platforms": ["desktop", "server", "android"],
            "fallback_policy": "fail_closed", "delegation_policy": "never",
            "resource_limits": {"timeout_ms": MAX_TIMEOUT_MS, "max_results": MAX_RESULTS, "max_output_bytes": MAX_OUTPUT_BYTES, "max_model_calls": 0},
            "registry_generation": 1, "availability": "unavailable", "unavailable_reason": "canonical-source-or-host-not-activated",
        }, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def invoke(self, request_id: str, activation_id: str, expert_operation: str, expected_registry_generation: int, expected_runtime_generation: int, input_json: str = "{}") -> str:
        if type(expert_operation) is not str or expert_operation not in ALLOWED_OPERATIONS:
            raise PythonExpertAdapterError("unsupported-expert-operation")
        if type(request_id) is not str or REQUEST_ID_RE.fullmatch(request_id) is None:
            raise PythonExpertAdapterError("invalid-request-id")
        if type(activation_id) is not str or ACTIVATION_ID_RE.fullmatch(activation_id) is None:
            raise PythonExpertAdapterError("invalid-activation-id")
        registry_generation = _validate_generation(expected_registry_generation, "registry-generation")
        runtime_generation = _validate_generation(expected_runtime_generation, "runtime-generation")
        payload = _decode_input(input_json, expert_operation)
        runtime = self._runtime
        resolver = getattr(runtime, "resolve_capability", None)
        invoker = getattr(runtime, "invoke_capability", None)
        if not callable(resolver) or not callable(invoker):
            raise PythonExpertAdapterError("expert-host-composition-unavailable")
        request = {"protocol": PROTOCOL, "request_id": request_id, "operation": "expert.invoke", "activation_id": activation_id, "expert_id": EXPERT_ID, "expert_operation": expert_operation, "expected_registry_generation": registry_generation, "expected_runtime_generation": runtime_generation, "input": payload, "limits": {"timeout_ms": MAX_TIMEOUT_MS, "max_results": MAX_RESULTS, "max_output_bytes": MAX_OUTPUT_BYTES, "max_model_calls": 0}}
        try:
            result = invoker(resolver(HOST_CAPABILITY), request)
        except PythonExpertAdapterError:
            raise
        except Exception as error:
            raise PythonExpertAdapterError("expert-host-invocation-failed") from error
        if type(result) is not dict:
            raise PythonExpertAdapterError("invalid-expert-result")
        _validate_result(result, request_id=request_id, activation_id=activation_id, operation=expert_operation, registry_generation=registry_generation, runtime_generation=runtime_generation)
        try:
            encoded = json.dumps(dict(result), allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError, RecursionError) as error:
            raise PythonExpertAdapterError("invalid-expert-result-json") from error
        if len(encoded.encode("utf-8")) > MAX_OUTPUT_BYTES:
            raise PythonExpertAdapterError("expert-result-too-large")
        return encoded

    def tools(self):
        return ()


def create_plugin() -> ZaraPythonExpertPlugin:
    return ZaraPythonExpertPlugin()
