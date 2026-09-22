from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from zara.plugins import PluginMetadata, ServicePlugin

PLUGIN_VERSION = "0.1.0"
PROTOCOL = "ZARA-EXPERT/1"
EXPERT_ID = "zara:expert/prolog"
PACKAGE_NAMESPACE = "zara-prolog-expert"
EXPERT_NAME = "PrologExpert"
SOURCE_REFERENCE = "dotfiles:.zara/experts/prolog"
UPSTREAM_CONTRACT = "lost-rob0t/prolog-rlm#495"
HOST_CAPABILITY = "expert.invoke"
MANIFEST_DIGEST = "sha256:8adf9bb1abd4aa16e46e0b97817762e4f34c8468ec2883d23a5fb96a780bca1b"
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
RESULT_ERROR_CODES = frozenset({"invalid_input", "ambiguity", "unsupported_operation", "unsupported_backend", "incompatible_protocol", "denied", "approval_required", "stale_generation", "unavailable", "deadline_exceeded", "budget_exceeded", "cancelled", "interrupted", "unknown_external_outcome"})
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
LANGUAGE_BOUNDARIES = {"language": "prolog", "extensions": (".pl", ".pro", ".prolog"), "applicability_keywords": ("prolog", "swi-prolog", "dcg"), "evidence_topics": ("syntax", "predicates", "modules", "dcg", "diagnostics", "style", "repair-verification")}
SOURCE_LOCK_FIELDS = frozenset({"schema_version", "expert_id", "adapter_version", "canonical_source", "runtime_contract", "zara_contract"})
CANONICAL_SOURCE_FIELDS = frozenset({"repository", "path", "issue", "producer_pr", "commit"})
RUNTIME_CONTRACT_FIELDS = frozenset({"repository", "issue"})
ZARA_CONTRACT_FIELDS = frozenset({"repository", "issue", "schema_pr"})
CANONICAL_SOURCE_ISSUE = 292
CANONICAL_SOURCE_PRODUCER_PR = 297
ZARA_CONTRACT_REPOSITORY = "lost-rob0t/zara"
ZARA_CONTRACT_ISSUE = 1233
ZARA_CONTRACT_SCHEMA_PR = 1273


class PrologExpertAdapterError(RuntimeError):
    """Fail closed; this adapter has no model/provider fallback."""


def _source_lock_path() -> Path:
    return Path(__file__).resolve().parents[2] / "expert-source.lock.json"


def _reject_duplicate_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if type(key) is not str or key in result:
            raise ValueError("duplicate-json-key")
        result[key] = value
    return result


def _validate_source_lock() -> None:
    try:
        raw = _source_lock_path().read_bytes()
    except OSError as error:
        raise PrologExpertAdapterError("source-lock-unavailable") from error
    if "sha256:" + hashlib.sha256(raw).hexdigest() != MANIFEST_DIGEST:
        raise PrologExpertAdapterError("source-lock-digest-mismatch")
    try:
        lock = json.loads(
            raw,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            object_pairs_hook=_reject_duplicate_object_pairs,
        )
    except (TypeError, UnicodeDecodeError, ValueError) as error:
        raise PrologExpertAdapterError("source-lock-invalid") from error
    if type(lock) is not dict:
        raise PrologExpertAdapterError("source-lock-invalid")
    canonical = lock.get("canonical_source")
    runtime_contract = lock.get("runtime_contract")
    zara_contract = lock.get("zara_contract")
    runtime_repo, runtime_issue = UPSTREAM_CONTRACT.rsplit("#", 1)
    if not (
        set(lock) == SOURCE_LOCK_FIELDS
        and type(lock.get("schema_version")) is int and lock.get("schema_version") == 1
        and type(lock.get("expert_id")) is str and lock.get("expert_id") == EXPERT_ID
        and type(lock.get("adapter_version")) is str and lock.get("adapter_version") == PLUGIN_VERSION
        and type(canonical) is dict and set(canonical) == CANONICAL_SOURCE_FIELDS
        and canonical.get("repository") == "lost-rob0t/dotfiles"
        and canonical.get("path") == SOURCE_REFERENCE.removeprefix("dotfiles:")
        and type(canonical.get("issue")) is int and canonical.get("issue") == CANONICAL_SOURCE_ISSUE
        and type(canonical.get("producer_pr")) is int and canonical.get("producer_pr") == CANONICAL_SOURCE_PRODUCER_PR
        and type(canonical.get("commit")) is str and re.fullmatch(r"[a-f0-9]{40}", canonical["commit"]) is not None
        and type(runtime_contract) is dict and set(runtime_contract) == RUNTIME_CONTRACT_FIELDS
        and runtime_contract.get("repository") == runtime_repo
        and type(runtime_contract.get("issue")) is int and str(runtime_contract.get("issue")) == runtime_issue
        and type(zara_contract) is dict and set(zara_contract) == ZARA_CONTRACT_FIELDS
        and zara_contract.get("repository") == ZARA_CONTRACT_REPOSITORY
        and type(zara_contract.get("issue")) is int and zara_contract.get("issue") == ZARA_CONTRACT_ISSUE
        and type(zara_contract.get("schema_pr")) is int and zara_contract.get("schema_pr") == ZARA_CONTRACT_SCHEMA_PR
    ):
        raise PrologExpertAdapterError("source-lock-identity-mismatch")
    try:
        from zara_expert import language_family as language_family_module
    except ImportError:
        return
    try:
        specs = tuple(spec for spec in language_family_module.language_family_specs() if getattr(spec, "key", None) == LANGUAGE_BOUNDARIES["language"])
    except Exception as error:
        raise PrologExpertAdapterError("source-lock-host-unavailable") from error
    if len(specs) != 1:
        raise PrologExpertAdapterError("source-lock-host-mismatch")
    spec = specs[0]
    if not (
        getattr(spec, "expert_id", None) == EXPERT_ID
        and getattr(spec, "source_reference", None) == SOURCE_REFERENCE
        and getattr(spec, "upstream_issue", None) == UPSTREAM_CONTRACT
        and tuple(getattr(spec, "extensions", ())) == tuple(LANGUAGE_BOUNDARIES["extensions"])
        and tuple(getattr(spec, "applicability_keywords", ())) == tuple(LANGUAGE_BOUNDARIES["applicability_keywords"])
    ):
        raise PrologExpertAdapterError("source-lock-host-mismatch")


def _validate_generation(value: object, field: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_GENERATION:
        raise PrologExpertAdapterError(f"invalid-{field}")
    return value


def _decode_input(input_json: str, operation: str) -> dict[str, Any]:
    if type(input_json) is not str:
        raise PrologExpertAdapterError("input-must-be-json-text")
    if len(input_json.encode("utf-8")) > MAX_INPUT_BYTES:
        raise PrologExpertAdapterError("input-too-large")
    try:
        payload = json.loads(input_json, parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
    except (TypeError, ValueError) as error:
        raise PrologExpertAdapterError("invalid-input-json") from error
    if type(payload) is not dict:
        raise PrologExpertAdapterError("input-must-be-object")
    declared = {field["name"]: field for field in OPERATION_FIELDS[operation]}
    if set(payload) - set(declared):
        raise PrologExpertAdapterError("unknown-operation-input")
    for name, field in declared.items():
        if field["required"] and name not in payload:
            raise PrologExpertAdapterError("missing-operation-input")
        if name in payload and type(payload[name]) is not str:
            raise PrologExpertAdapterError("invalid-operation-input")
    return payload


def _validate_data_tree(value: object, depth: int = 0) -> None:
    if depth > 64:
        raise PrologExpertAdapterError("invalid-expert-data-json")
    if type(value) is dict:
        for key, child in value.items():
            if type(key) is not str:
                raise PrologExpertAdapterError("invalid-expert-data-json")
            _validate_data_tree(child, depth + 1)
        return
    if type(value) in (list, tuple):
        for child in value:
            _validate_data_tree(child, depth + 1)
        return
    if type(value) is float and not math.isfinite(value):
        raise PrologExpertAdapterError("invalid-expert-data-json")
    if value is None or type(value) in (str, int, bool, float):
        return
    raise PrologExpertAdapterError("invalid-expert-data-json")


def _validate_output(operation: str, verdict: str, data: object) -> None:
    if type(data) is not dict:
        raise PrologExpertAdapterError("invalid-expert-output")
    _validate_data_tree(data)
    if verdict != "succeeded":
        if data:
            raise PrologExpertAdapterError("invalid-expert-output")
        return
    declared = {field["name"]: field for field in OPERATION_OUTPUT_FIELDS[operation]}
    if set(data) - set(declared):
        raise PrologExpertAdapterError("invalid-expert-output")
    for name, field in declared.items():
        if field["required"] and name not in data:
            raise PrologExpertAdapterError("invalid-expert-output")
        if name not in data:
            continue
        value, kind = data[name], field["type"]
        valid = type(value) is bool if kind == "boolean" else type(value) is dict if kind == "object" else type(value) is list if kind == "list" else False
        if not valid:
            raise PrologExpertAdapterError("invalid-expert-output")


def _validate_result_metadata(result: Mapping[str, object]) -> None:
    if any(type(field) is not str or field not in RESULT_FIELDS for field in result):
        raise PrologExpertAdapterError("unknown-expert-result-field")
    error_code = result.get("error_code")
    if error_code is not None and (type(error_code) is not str or error_code not in RESULT_ERROR_CODES):
        raise PrologExpertAdapterError("invalid-expert-error-code")
    error_message = result.get("error_message", "")
    if type(error_message) is not str or len(error_message) > MAX_STRING_LENGTH:
        raise PrologExpertAdapterError("invalid-expert-error-message")
    if type(result.get("replayed", False)) is not bool:
        raise PrologExpertAdapterError("invalid-expert-replayed")


def _validate_result(result: Mapping[str, object], *, request_id: str, activation_id: str, operation: str, registry_generation: int, runtime_generation: int) -> None:
    _validate_result_metadata(result)
    invocation_id = result.get("invocation_id")
    if type(invocation_id) is not str or INVOCATION_ID_RE.fullmatch(invocation_id) is None:
        raise PrologExpertAdapterError("invalid-expert-invocation-id")
    expected = {"protocol": PROTOCOL, "request_id": request_id, "activation_id": activation_id, "expert_id": EXPERT_ID, "expert_version": PLUGIN_VERSION, "manifest_digest": MANIFEST_DIGEST, "expert_operation": operation}
    if any(result.get(key) != value for key, value in expected.items()):
        raise PrologExpertAdapterError("expert-result-identity-mismatch")
    if type(result.get("resolved_registry_generation")) is not int or result.get("resolved_registry_generation") != registry_generation:
        raise PrologExpertAdapterError("stale-expert-result")
    if type(result.get("resolved_runtime_generation")) is not int or result.get("resolved_runtime_generation") != runtime_generation:
        raise PrologExpertAdapterError("stale-expert-result")
    verdict = result.get("verdict")
    if type(verdict) is not str or verdict not in RESULT_VERDICTS:
        raise PrologExpertAdapterError("invalid-expert-verdict")
    usage = result.get("usage")
    if type(usage) is not dict or set(usage) != USAGE_FIELDS or type(usage.get("model_calls")) is not int or usage.get("model_calls") != 0:
        raise PrologExpertAdapterError("zero-model-proof-missing")
    receipts = result.get("effect_receipts")
    if type(receipts) not in (list, tuple):
        raise PrologExpertAdapterError("read-only-effect-proof-missing")
    if receipts:
        raise PrologExpertAdapterError("read-only-effect-leak")
    evidence = result.get("evidence_refs")
    if type(evidence) not in (list, tuple) or len(evidence) > MAX_EVIDENCE_REFS or any(type(item) is not str for item in evidence):
        raise PrologExpertAdapterError("invalid-expert-evidence")
    if verdict == "cancelled" and evidence:
        raise PrologExpertAdapterError("cancelled-expert-output-leak")
    _validate_output(operation, verdict, result.get("data"))


def _operation_descriptor(operation: str) -> dict[str, object]:
    return {"operation_id": operation, "input_schema": {"fields": [dict(field) for field in OPERATION_FIELDS[operation]]}, "output_schema": {"fields": [dict(field) for field in OPERATION_OUTPUT_FIELDS[operation]]}}


class ZaraPrologExpertPlugin(ServicePlugin):
    metadata = PluginMetadata(name=PACKAGE_NAMESPACE, version=PLUGIN_VERSION, api_version="1", description="Pure-symbolic PrologExpert adapter over the canonical Zara expert host")

    def __init__(self) -> None:
        self._runtime: Any | None = None

    def start(self, runtime: Any) -> None:
        self._runtime = runtime

    def stop(self) -> None:
        self._runtime = None

    def descriptor(self) -> str:
        _validate_source_lock()
        return json.dumps({
            "protocol": PROTOCOL, "expert_id": EXPERT_ID, "expert_version": PLUGIN_VERSION,
            "package_namespace": PACKAGE_NAMESPACE, "manifest_digest": MANIFEST_DIGEST,
            "name": EXPERT_NAME, "description": "Pure-symbolic PrologExpert product adapter",
            "source_reference": SOURCE_REFERENCE, "reasoning_kind": "symbolic",
            "operations": [_operation_descriptor(operation) for operation in sorted(ALLOWED_OPERATIONS)],
            "applicability": {"keywords": list(LANGUAGE_BOUNDARIES["applicability_keywords"])},
            "required_capabilities": [HOST_CAPABILITY], "possible_effects": ["none"],
            "supported_engines": ["swipl"], "supported_platforms": ["desktop", "server", "android"],
            "fallback_policy": "fail_closed", "delegation_policy": "never",
            "resource_limits": {"timeout_ms": MAX_TIMEOUT_MS, "max_results": MAX_RESULTS, "max_output_bytes": MAX_OUTPUT_BYTES, "max_model_calls": 0},
            "registry_generation": 1, "availability": "unavailable", "unavailable_reason": "canonical-source-or-host-not-activated",
        }, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def invoke(self, request_id: str, activation_id: str, expert_operation: str, expected_registry_generation: int, expected_runtime_generation: int, input_json: str = "{}") -> str:
        _validate_source_lock()
        if type(expert_operation) is not str or expert_operation not in ALLOWED_OPERATIONS:
            raise PrologExpertAdapterError("unsupported-expert-operation")
        if type(request_id) is not str or REQUEST_ID_RE.fullmatch(request_id) is None:
            raise PrologExpertAdapterError("invalid-request-id")
        if type(activation_id) is not str or ACTIVATION_ID_RE.fullmatch(activation_id) is None:
            raise PrologExpertAdapterError("invalid-activation-id")
        registry_generation = _validate_generation(expected_registry_generation, "registry-generation")
        runtime_generation = _validate_generation(expected_runtime_generation, "runtime-generation")
        payload = _decode_input(input_json, expert_operation)
        runtime = self._runtime
        resolver, invoker = getattr(runtime, "resolve_capability", None), getattr(runtime, "invoke_capability", None)
        if not callable(resolver) or not callable(invoker):
            raise PrologExpertAdapterError("expert-host-composition-unavailable")
        request = {"protocol": PROTOCOL, "request_id": request_id, "operation": "expert.invoke", "activation_id": activation_id, "expert_id": EXPERT_ID, "expert_operation": expert_operation, "expected_registry_generation": registry_generation, "expected_runtime_generation": runtime_generation, "input": payload, "limits": {"timeout_ms": MAX_TIMEOUT_MS, "max_results": MAX_RESULTS, "max_output_bytes": MAX_OUTPUT_BYTES, "max_model_calls": 0}}
        try:
            result = invoker(resolver(HOST_CAPABILITY), request)
        except PrologExpertAdapterError:
            raise
        except Exception as error:
            raise PrologExpertAdapterError("expert-host-invocation-failed") from error
        _validate_source_lock()
        if type(result) is not dict:
            raise PrologExpertAdapterError("invalid-expert-result")
        _validate_result(result, request_id=request_id, activation_id=activation_id, operation=expert_operation, registry_generation=registry_generation, runtime_generation=runtime_generation)
        try:
            encoded = json.dumps(result, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            snapshot = json.loads(encoded, parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
        except (TypeError, ValueError, RecursionError) as error:
            raise PrologExpertAdapterError("invalid-expert-result-json") from error
        if len(encoded.encode("utf-8")) > MAX_OUTPUT_BYTES:
            raise PrologExpertAdapterError("expert-result-too-large")
        if type(snapshot) is not dict:
            raise PrologExpertAdapterError("invalid-expert-result")
        _validate_result(snapshot, request_id=request_id, activation_id=activation_id, operation=expert_operation, registry_generation=registry_generation, runtime_generation=runtime_generation)
        return encoded

    def tools(self):
        return ()


def create_plugin() -> ZaraPrologExpertPlugin:
    return ZaraPrologExpertPlugin()
