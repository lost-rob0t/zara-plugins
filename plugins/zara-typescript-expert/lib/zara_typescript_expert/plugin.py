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
EXPERT_ID = "zara:expert/typescript"
PACKAGE_NAMESPACE = "zara-typescript-expert"
EXPERT_NAME = "TypeScriptExpert"
SOURCE_REFERENCE = "source:dotfiles.typescript-expert"
UPSTREAM_CONTRACT = "lost-rob0t/prolog-rlm#500"
HOST_CAPABILITY = "expert.invoke"
MANIFEST_DIGEST = "sha256:31e50b1ad7c2656032cf508f2f47623ad48ed4e8fee3ef40aef5fa134af73ba4"
MAX_INPUT_BYTES = 8192
MAX_OUTPUT_BYTES = 65536
MAX_TIMEOUT_MS = 3000
MAX_RESULTS = 32
MAX_INPUT_DEPTH = 8
MAX_INPUT_KEYS = 32
MAX_INPUT_LIST = 64
MAX_STRING_LENGTH = 4096
MAX_GENERATION = 2_147_483_647
MAX_RESULT_NODES = 65_536
MAX_EVIDENCE_REFS = 32
MAX_EVIDENCE_REF_LENGTH = 128
REQUEST_ID_RE = re.compile(r"^[!-~]{1,128}$")
ACTIVATION_ID_RE = re.compile(r"^act:[a-f0-9]{32}$")
INVOCATION_ID_RE = re.compile(r"^inv:[a-f0-9]{32}$")
RESULT_VERDICTS = frozenset(
    {"succeeded", "failed", "unknown", "blocked", "unsupported", "cancelled", "error"}
)
RESULT_ERROR_CODES = frozenset(
    {
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
    }
)
RESULT_FIELDS = frozenset(
    {
        "protocol",
        "request_id",
        "invocation_id",
        "activation_id",
        "expert_id",
        "expert_version",
        "manifest_digest",
        "expert_operation",
        "resolved_registry_generation",
        "resolved_runtime_generation",
        "verdict",
        "data",
        "evidence_refs",
        "usage",
        "effect_receipts",
        "error_code",
        "error_message",
        "replayed",
    }
)
USAGE_FIELDS = frozenset({"model_calls"})
OPERATION_FIELDS: dict[str, tuple[dict[str, object], ...]] = {
    "match": (
        {"name": "path", "type": "string", "required": True},
        {"name": "source_generation", "type": "reference", "required": True},
    ),
    "inspect": (
        {"name": "source", "type": "string", "required": True},
        {"name": "source_generation", "type": "reference", "required": True},
    ),
    "diagnose": (
        {"name": "source", "type": "string", "required": True},
        {"name": "source_generation", "type": "reference", "required": True},
    ),
    "repair.preview": (
        {"name": "source", "type": "string", "required": True},
        {"name": "source_generation", "type": "reference", "required": True},
        {"name": "diagnostic_ref", "type": "reference", "required": True},
    ),
    "repair.verify": (
        {"name": "original_source", "type": "string", "required": True},
        {"name": "candidate_source", "type": "string", "required": True},
        {"name": "source_generation", "type": "reference", "required": True},
    ),
    "style.rules": (
        {"name": "source", "type": "string", "required": True},
        {"name": "project_style", "type": "reference", "required": True},
    ),
    "explain": (
        {"name": "decision_ref", "type": "reference", "required": True},
        {"name": "source_generation", "type": "reference", "required": True},
    ),
}
OPERATION_OUTPUT_FIELDS: dict[str, tuple[dict[str, object], ...]] = {
    "match": (
        {"name": "applicable", "type": "boolean", "required": True},
        {"name": "evidence_refs", "type": "list", "required": False},
        {"name": "explanation_refs", "type": "list", "required": False},
    ),
    "inspect": (
        {"name": "result", "type": "object", "required": True},
        {"name": "evidence_refs", "type": "list", "required": False},
        {"name": "explanation_refs", "type": "list", "required": False},
    ),
    "diagnose": (
        {"name": "diagnostics", "type": "list", "required": True},
        {"name": "evidence_refs", "type": "list", "required": False},
        {"name": "explanation_refs", "type": "list", "required": False},
    ),
    "repair.preview": (
        {"name": "repair", "type": "object", "required": True},
        {"name": "evidence_refs", "type": "list", "required": False},
        {"name": "explanation_refs", "type": "list", "required": False},
    ),
    "repair.verify": (
        {"name": "verified", "type": "boolean", "required": True},
        {"name": "postcondition_evidence", "type": "object", "required": True},
        {"name": "evidence_refs", "type": "list", "required": False},
        {"name": "explanation_refs", "type": "list", "required": False},
    ),
    "style.rules": (
        {"name": "style_rules", "type": "list", "required": True},
        {"name": "style_provenance", "type": "list", "required": True},
        {"name": "evidence_refs", "type": "list", "required": False},
        {"name": "explanation_refs", "type": "list", "required": False},
    ),
    "explain": (
        {"name": "explanation", "type": "object", "required": True},
        {"name": "evidence_refs", "type": "list", "required": False},
        {"name": "explanation_refs", "type": "list", "required": False},
    ),
}
ALLOWED_OPERATIONS = frozenset(OPERATION_FIELDS)
LANGUAGE_BOUNDARIES = {
    "language": "typescript",
    "extensions": (".ts", ".tsx", ".mts", ".cts"),
    "evidence_topics": (
        "syntax",
        "modules",
        "tsx",
        "types",
        "diagnostics",
        "style",
        "repair-verification",
    ),
    "project_metadata_policy": "not_applicable",
    "jvm_project_metadata": False,
    "gradle_project_metadata": False,
    "android_project_metadata": False,
}
SOURCE_LOCK_FIELDS = frozenset(
    {
        "schema_version",
        "expert_id",
        "adapter_version",
        "canonical_source",
        "runtime_contract",
        "zara_contract",
    }
)
CANONICAL_SOURCE_FIELDS = frozenset(
    {"repository", "path", "issue", "producer_pr", "commit"}
)
RUNTIME_CONTRACT_FIELDS = frozenset({"repository", "issue"})
ZARA_CONTRACT_FIELDS = frozenset({"repository", "issue", "schema_pr"})
CANONICAL_SOURCE_REFERENCE = "dotfiles:.zara/experts/typescript"
CANONICAL_SOURCE_ISSUE = 292
CANONICAL_SOURCE_PRODUCER_PR = 299
ZARA_CONTRACT_REPOSITORY = "lost-rob0t/zara"
ZARA_CONTRACT_ISSUE = 1233
ZARA_CONTRACT_SCHEMA_PR = 1273


class TypeScriptExpertAdapterError(RuntimeError):
    """Fail closed: this adapter never falls back to a provider or model."""


def _source_lock_path() -> Path:
    return Path(__file__).resolve().parents[2] / "expert-source.lock.json"


def _reject_source_lock_duplicate_object_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, child in pairs:
        if type(key) is not str or key in value:
            raise ValueError("duplicate-json-key")
        value[key] = child
    return value


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _validate_source_lock() -> None:
    try:
        raw = _source_lock_path().read_bytes()
    except OSError as error:
        raise TypeScriptExpertAdapterError("source-lock-unavailable") from error
    if "sha256:" + hashlib.sha256(raw).hexdigest() != MANIFEST_DIGEST:
        raise TypeScriptExpertAdapterError("source-lock-digest-mismatch")
    try:
        lock = json.loads(
            raw,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_source_lock_duplicate_object_pairs,
        )
    except (TypeError, UnicodeDecodeError, ValueError) as error:
        raise TypeScriptExpertAdapterError("source-lock-invalid") from error
    if type(lock) is not dict:
        raise TypeScriptExpertAdapterError("source-lock-invalid")

    canonical = lock.get("canonical_source")
    runtime_contract = lock.get("runtime_contract")
    zara_contract = lock.get("zara_contract")
    runtime_repo, runtime_issue = UPSTREAM_CONTRACT.rsplit("#", 1)
    if not (
        set(lock) == SOURCE_LOCK_FIELDS
        and type(lock.get("schema_version")) is int
        and lock.get("schema_version") == 1
        and type(lock.get("expert_id")) is str
        and lock.get("expert_id") == EXPERT_ID
        and type(lock.get("adapter_version")) is str
        and lock.get("adapter_version") == PLUGIN_VERSION
        and type(canonical) is dict
        and set(canonical) == CANONICAL_SOURCE_FIELDS
        and canonical.get("repository") == "lost-rob0t/dotfiles"
        and canonical.get("path") == CANONICAL_SOURCE_REFERENCE.removeprefix("dotfiles:")
        and type(canonical.get("issue")) is int
        and canonical.get("issue") == CANONICAL_SOURCE_ISSUE
        and type(canonical.get("producer_pr")) is int
        and canonical.get("producer_pr") == CANONICAL_SOURCE_PRODUCER_PR
        and type(canonical.get("commit")) is str
        and re.fullmatch(r"[a-f0-9]{40}", canonical["commit"]) is not None
        and type(runtime_contract) is dict
        and set(runtime_contract) == RUNTIME_CONTRACT_FIELDS
        and runtime_contract.get("repository") == runtime_repo
        and type(runtime_contract.get("issue")) is int
        and str(runtime_contract.get("issue")) == runtime_issue
        and type(zara_contract) is dict
        and set(zara_contract) == ZARA_CONTRACT_FIELDS
        and zara_contract.get("repository") == ZARA_CONTRACT_REPOSITORY
        and type(zara_contract.get("issue")) is int
        and zara_contract.get("issue") == ZARA_CONTRACT_ISSUE
        and type(zara_contract.get("schema_pr")) is int
        and zara_contract.get("schema_pr") == ZARA_CONTRACT_SCHEMA_PR
    ):
        raise TypeScriptExpertAdapterError("source-lock-identity-mismatch")

    try:
        from zara_expert import language_family as language_family_module
    except ImportError:
        return
    try:
        specs = tuple(
            spec
            for spec in language_family_module.language_family_specs()
            if getattr(spec, "key", None) == "typescript"
        )
    except Exception as error:
        raise TypeScriptExpertAdapterError("source-lock-host-unavailable") from error
    if len(specs) != 1:
        raise TypeScriptExpertAdapterError("source-lock-host-mismatch")
    spec = specs[0]
    if not (
        getattr(spec, "expert_id", None) == EXPERT_ID
        and getattr(spec, "source_reference", None) == CANONICAL_SOURCE_REFERENCE
        and getattr(spec, "upstream_issue", None) == UPSTREAM_CONTRACT
        and tuple(getattr(spec, "extensions", ())) == tuple(LANGUAGE_BOUNDARIES["extensions"])
        and tuple(getattr(spec, "applicability_keywords", ()))
        == ("typescript", "ts", "tsx", "mts", "cts")
    ):
        raise TypeScriptExpertAdapterError("source-lock-host-mismatch")


def _provenance_evidence_ref() -> str:
    payload = {
        "expert_id": EXPERT_ID,
        "expert_version": PLUGIN_VERSION,
        "manifest_digest": MANIFEST_DIGEST,
        "source_reference": SOURCE_REFERENCE,
        "upstream_contract": UPSTREAM_CONTRACT,
        "zara_contract": f"{ZARA_CONTRACT_REPOSITORY}#{ZARA_CONTRACT_ISSUE}",
        "zara_schema_pr": ZARA_CONTRACT_SCHEMA_PR,
    }
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "evidence:expert-provenance:sha256:" + hashlib.sha256(encoded).hexdigest()


def _validate_json_tree(value: object, *, depth: int = 0) -> None:
    if depth > MAX_INPUT_DEPTH:
        raise TypeScriptExpertAdapterError("input-structure-too-complex")
    if isinstance(value, dict):
        if len(value) > MAX_INPUT_KEYS:
            raise TypeScriptExpertAdapterError("input-object-too-large")
        for key, child in value.items():
            if not isinstance(key, str) or not key or len(key) > 64:
                raise TypeScriptExpertAdapterError("invalid-input-key")
            _validate_json_tree(child, depth=depth + 1)
        return
    if isinstance(value, list):
        if len(value) > MAX_INPUT_LIST:
            raise TypeScriptExpertAdapterError("input-array-too-large")
        for child in value:
            _validate_json_tree(child, depth=depth + 1)
        return
    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            raise TypeScriptExpertAdapterError("input-string-too-large")
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise TypeScriptExpertAdapterError("invalid-input-number")
    if value is None or isinstance(value, (bool, int, float)):
        return
    raise TypeScriptExpertAdapterError("invalid-input-value")


def _validate_generation(value: object, field: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_GENERATION:
        raise TypeScriptExpertAdapterError(f"invalid-{field}")
    return value


def _validate_request_id(value: object) -> str:
    if type(value) is not str or REQUEST_ID_RE.fullmatch(value) is None:
        raise TypeScriptExpertAdapterError("invalid-request-id")
    return value


def _validate_activation_id(value: object) -> str:
    if type(value) is not str or ACTIVATION_ID_RE.fullmatch(value) is None:
        raise TypeScriptExpertAdapterError("invalid-activation-id")
    return value


def _check_field(field: Mapping[str, object], value: object) -> None:
    if field["type"] in {"string", "reference"} and not isinstance(value, str):
        raise TypeScriptExpertAdapterError("invalid-operation-input")


def _validate_operation_input(operation: str, payload: Mapping[str, object]) -> None:
    declared = {field["name"]: field for field in OPERATION_FIELDS[operation]}
    if set(payload) - set(declared):
        raise TypeScriptExpertAdapterError("unknown-operation-input")
    for name, field in declared.items():
        if field["required"] and name not in payload:
            raise TypeScriptExpertAdapterError("missing-operation-input")
        if name in payload:
            _check_field(field, payload[name])


def _validate_output_field(field: Mapping[str, object], value: object) -> None:
    kind = field["type"]
    valid = (
        type(value) is bool
        if kind == "boolean"
        else isinstance(value, Mapping)
        if kind == "object"
        else isinstance(value, list)
        if kind == "list"
        else False
    )
    if not valid:
        raise TypeScriptExpertAdapterError("invalid-expert-output")


def _validate_operation_output(operation: str, verdict: str, data: object) -> None:
    if not isinstance(data, Mapping):
        raise TypeScriptExpertAdapterError("invalid-expert-output")
    if verdict != "succeeded":
        if data:
            raise TypeScriptExpertAdapterError("invalid-expert-output")
        return
    declared = {field["name"]: field for field in OPERATION_OUTPUT_FIELDS[operation]}
    if set(data) - set(declared):
        raise TypeScriptExpertAdapterError("invalid-expert-output")
    for name, field in declared.items():
        if field["required"] and name not in data:
            raise TypeScriptExpertAdapterError("invalid-expert-output")
        if name in data:
            _validate_output_field(field, data[name])


def _validate_result_data_tree(data: dict[str, object]) -> None:
    stack: list[tuple[bool, object]] = [(False, data)]
    active_containers: set[int] = set()
    nodes = 0
    while stack:
        exiting, current = stack.pop()
        if exiting:
            active_containers.remove(id(current))
            continue

        nodes += 1
        if nodes > MAX_RESULT_NODES:
            raise TypeScriptExpertAdapterError("invalid-expert-data-json")

        if type(current) is dict:
            container_id = id(current)
            if container_id in active_containers:
                raise TypeScriptExpertAdapterError("invalid-expert-data-json")
            active_containers.add(container_id)
            stack.append((True, current))
            for key, child in current.items():
                if type(key) is not str:
                    raise TypeScriptExpertAdapterError("invalid-expert-data-json")
                stack.append((False, child))
        elif type(current) is list:
            container_id = id(current)
            if container_id in active_containers:
                raise TypeScriptExpertAdapterError("invalid-expert-data-json")
            active_containers.add(container_id)
            stack.append((True, current))
            stack.extend((False, child) for child in current)
        elif type(current) is float:
            if not math.isfinite(current):
                raise TypeScriptExpertAdapterError("invalid-expert-data-json")
        elif current is None or type(current) in (str, int, bool):
            continue
        else:
            raise TypeScriptExpertAdapterError("invalid-expert-data-json")


def _validate_result_payload(
    result: Mapping[str, object],
) -> tuple[dict[str, object], list[str]]:
    data = result.get("data")
    if type(data) is not dict:
        raise TypeScriptExpertAdapterError("invalid-expert-data")
    _validate_result_data_tree(data)

    evidence_refs = result.get("evidence_refs")
    if type(evidence_refs) is not list:
        raise TypeScriptExpertAdapterError("invalid-expert-evidence")
    if len(evidence_refs) > MAX_EVIDENCE_REFS:
        raise TypeScriptExpertAdapterError("invalid-expert-evidence")
    for evidence_ref in evidence_refs:
        if type(evidence_ref) is not str or not evidence_ref or len(evidence_ref) > MAX_EVIDENCE_REF_LENGTH:
            raise TypeScriptExpertAdapterError("invalid-expert-evidence")
    return data, evidence_refs


def _validate_result_usage(result: Mapping[str, object]) -> None:
    usage = result.get("usage")
    if usage is None:
        raise TypeScriptExpertAdapterError("zero-model-proof-missing")
    if type(usage) is not dict:
        raise TypeScriptExpertAdapterError("invalid-expert-usage")
    for field in usage:
        if type(field) is not str or field not in USAGE_FIELDS:
            raise TypeScriptExpertAdapterError("unknown-expert-usage-field")
    model_calls = usage.get("model_calls")
    if type(model_calls) is not int or model_calls != 0:
        raise TypeScriptExpertAdapterError("zero-model-proof-missing")


def _validate_result_metadata(result: Mapping[str, object]) -> None:
    for field in result:
        if type(field) is not str or field not in RESULT_FIELDS:
            raise TypeScriptExpertAdapterError("unknown-expert-result-field")

    error_code = result.get("error_code")
    if error_code is not None and (
        type(error_code) is not str or error_code not in RESULT_ERROR_CODES
    ):
        raise TypeScriptExpertAdapterError("invalid-expert-error-code")

    error_message = result.get("error_message", "")
    if type(error_message) is not str or len(error_message) > MAX_STRING_LENGTH:
        raise TypeScriptExpertAdapterError("invalid-expert-error-message")

    replayed = result.get("replayed", False)
    if type(replayed) is not bool:
        raise TypeScriptExpertAdapterError("invalid-expert-replayed")


def _operation_descriptor(operation: str) -> dict[str, object]:
    return {
        "operation_id": operation,
        "input_schema": {"fields": [dict(field) for field in OPERATION_FIELDS[operation]]},
        "output_schema": {
            "fields": [dict(field) for field in OPERATION_OUTPUT_FIELDS[operation]]
        },
    }


def _validate_result(
    result: Mapping[str, object],
    *,
    request_id: str,
    activation_id: str,
    expert_operation: str,
    registry_generation: int,
    runtime_generation: int,
) -> None:
    _validate_result_metadata(result)
    invocation_id = result.get("invocation_id")
    if type(invocation_id) is not str or INVOCATION_ID_RE.fullmatch(invocation_id) is None:
        raise TypeScriptExpertAdapterError("invalid-expert-invocation-id")
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
        actual = result.get(key)
        if type(actual) is not str or actual != value:
            raise TypeScriptExpertAdapterError("expert-result-identity-mismatch")
    resolved_registry_generation = result.get("resolved_registry_generation")
    resolved_runtime_generation = result.get("resolved_runtime_generation")
    if (
        type(resolved_registry_generation) is not int
        or resolved_registry_generation != registry_generation
        or type(resolved_runtime_generation) is not int
        or resolved_runtime_generation != runtime_generation
    ):
        raise TypeScriptExpertAdapterError("stale-expert-result")
    verdict = result.get("verdict")
    if verdict not in RESULT_VERDICTS:
        raise TypeScriptExpertAdapterError("invalid-expert-verdict")
    _validate_result_usage(result)
    receipts = result.get("effect_receipts")
    if type(receipts) is not list:
        raise TypeScriptExpertAdapterError("read-only-effect-proof-missing")
    if receipts:
        raise TypeScriptExpertAdapterError("read-only-effect-leak")

    data_value = result.get("data")
    evidence_value = result.get("evidence_refs")
    error_code = result.get("error_code")
    terminal_error = error_code in {"cancelled", "stale_generation"}
    if verdict == "succeeded" and terminal_error:
        raise TypeScriptExpertAdapterError("terminal-fence")
    if terminal_error:
        if isinstance(data_value, Mapping) and data_value:
            raise TypeScriptExpertAdapterError("terminal-fence")
        if isinstance(evidence_value, (list, tuple)) and evidence_value:
            raise TypeScriptExpertAdapterError("terminal-fence")
    if verdict == "cancelled":
        if not isinstance(data_value, Mapping) or data_value:
            raise TypeScriptExpertAdapterError("cancelled-expert-output-leak")
        if not isinstance(evidence_value, (list, tuple)) or evidence_value:
            raise TypeScriptExpertAdapterError("cancelled-expert-output-leak")
    _validate_operation_output(expert_operation, verdict, data_value)
    data, evidence_refs = _validate_result_payload(result)
    if terminal_error and (data or evidence_refs):
        raise TypeScriptExpertAdapterError("terminal-fence")


class ZaraTypeScriptExpertPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name=PACKAGE_NAMESPACE,
        version=PLUGIN_VERSION,
        api_version="1",
        description="Pure-symbolic TypeScriptExpert adapter over the canonical Zara language host",
    )

    def __init__(self) -> None:
        self._runtime: Any | None = None

    def start(self, runtime: Any) -> None:
        self._runtime = runtime

    def stop(self) -> None:
        self._runtime = None

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _decode_input(input_json: str) -> dict[str, Any]:
        if type(input_json) is not str:
            raise TypeScriptExpertAdapterError("input-must-be-json-text")
        if len(input_json.encode("utf-8")) > MAX_INPUT_BYTES:
            raise TypeScriptExpertAdapterError("input-too-large")
        try:
            value = json.loads(input_json, parse_constant=_reject_json_constant)
        except (TypeError, ValueError) as error:
            raise TypeScriptExpertAdapterError("invalid-input-json") from error
        if not isinstance(value, dict):
            raise TypeScriptExpertAdapterError("input-must-be-object")
        _validate_json_tree(value)
        return value

    def descriptor(self) -> str:
        _validate_source_lock()
        return self._json(
            {
                "protocol": PROTOCOL,
                "expert_id": EXPERT_ID,
                "expert_version": PLUGIN_VERSION,
                "package_namespace": PACKAGE_NAMESPACE,
                "manifest_digest": MANIFEST_DIGEST,
                "name": EXPERT_NAME,
                "description": "Pure-symbolic TypeScriptExpert adapter over the canonical Zara language host",
                "source_reference": SOURCE_REFERENCE,
                "reasoning_kind": "symbolic",
                "operations": [
                    _operation_descriptor(operation)
                    for operation in sorted(ALLOWED_OPERATIONS)
                ],
                "applicability": {"keywords": ["typescript", "ts", "tsx", "mts", "cts"]},
                "required_capabilities": [HOST_CAPABILITY],
                "possible_effects": ["none"],
                "supported_engines": ["swipl"],
                "supported_platforms": ["desktop", "server", "android"],
                "fallback_policy": "fail_closed",
                "delegation_policy": "never",
                "resource_limits": {
                    "timeout_ms": MAX_TIMEOUT_MS,
                    "max_results": MAX_RESULTS,
                    "max_output_bytes": MAX_OUTPUT_BYTES,
                    "max_model_calls": 0,
                },
                "registry_generation": 1,
                "availability": "unavailable",
                "unavailable_reason": "canonical-source-or-host-not-activated",
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
        _validate_source_lock()
        if expert_operation not in ALLOWED_OPERATIONS:
            raise TypeScriptExpertAdapterError("unsupported-expert-operation")
        request_id = _validate_request_id(request_id)
        activation_id = _validate_activation_id(activation_id)
        registry_generation = _validate_generation(
            expected_registry_generation, "registry-generation"
        )
        runtime_generation = _validate_generation(
            expected_runtime_generation, "runtime-generation"
        )
        payload = self._decode_input(input_json)
        _validate_operation_input(expert_operation, payload)
        runtime = self._runtime
        resolver = getattr(runtime, "resolve_capability", None)
        invoker = getattr(runtime, "invoke_capability", None)
        if not callable(resolver) or not callable(invoker):
            raise TypeScriptExpertAdapterError("expert-host-composition-unavailable")
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
            "limits": {
                "timeout_ms": MAX_TIMEOUT_MS,
                "max_results": MAX_RESULTS,
                "max_output_bytes": MAX_OUTPUT_BYTES,
                "max_model_calls": 0,
            },
        }
        try:
            handle = resolver(HOST_CAPABILITY)
            result = invoker(handle, request)
        except TypeScriptExpertAdapterError:
            raise
        except Exception as error:
            raise TypeScriptExpertAdapterError("expert-host-invocation-failed") from error
        _validate_source_lock()
        if type(result) is not dict:
            raise TypeScriptExpertAdapterError("invalid-expert-result")
        _validate_result(
            result,
            request_id=request_id,
            activation_id=activation_id,
            expert_operation=expert_operation,
            registry_generation=registry_generation,
            runtime_generation=runtime_generation,
        )
        try:
            owned_encoded = self._json(result)
            result = json.loads(owned_encoded, parse_constant=_reject_json_constant)
        except (TypeError, ValueError, RecursionError) as error:
            raise TypeScriptExpertAdapterError("invalid-expert-result-json") from error
        if type(result) is not dict:
            raise TypeScriptExpertAdapterError("invalid-expert-result")
        _validate_result(
            result,
            request_id=request_id,
            activation_id=activation_id,
            expert_operation=expert_operation,
            registry_generation=registry_generation,
            runtime_generation=runtime_generation,
        )
        if result["verdict"] == "succeeded":
            evidence = result["evidence_refs"]
            if any(item.startswith("evidence:expert-provenance:sha256:") for item in evidence):
                raise TypeScriptExpertAdapterError("provenance-evidence-namespace-conflict")
            provenance_ref = _provenance_evidence_ref()
            if provenance_ref not in evidence:
                if len(evidence) >= MAX_EVIDENCE_REFS:
                    raise TypeScriptExpertAdapterError("provenance-evidence-budget-exceeded")
                result = dict(result)
                result["evidence_refs"] = [*evidence, provenance_ref]
                _validate_result(
                    result,
                    request_id=request_id,
                    activation_id=activation_id,
                    expert_operation=expert_operation,
                    registry_generation=registry_generation,
                    runtime_generation=runtime_generation,
                )
        try:
            encoded = self._json(result)
            snapshot = json.loads(encoded, parse_constant=_reject_json_constant)
        except (TypeError, ValueError, RecursionError) as error:
            raise TypeScriptExpertAdapterError("invalid-expert-result-json") from error
        if len(encoded.encode("utf-8")) > MAX_OUTPUT_BYTES:
            raise TypeScriptExpertAdapterError("expert-result-too-large")
        if type(snapshot) is not dict:
            raise TypeScriptExpertAdapterError("invalid-expert-result")
        _validate_result(
            snapshot,
            request_id=request_id,
            activation_id=activation_id,
            expert_operation=expert_operation,
            registry_generation=registry_generation,
            runtime_generation=runtime_generation,
        )
        return encoded

    def tools(self):
        return ()


def create_plugin():
    return ZaraTypeScriptExpertPlugin()
