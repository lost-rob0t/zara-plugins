from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin


PLUGIN_VERSION = "0.1.0"
PROTOCOL = "ZARA-EXPERT/1"
EXPERT_ID = "zara:expert/bash"
SOURCE_REFERENCE = "dotfiles:.zara/experts/bash"
UPSTREAM_CONTRACT = "lost-rob0t/prolog-rlm#502"
SOURCE_ISSUE = 287
LANGUAGE_EXTENSIONS = (".sh", ".bash")
LANGUAGE_KEYWORDS = ("bash", "shell", "sh")
HOST_CAPABILITY = "expert.invoke"
MANIFEST_DIGEST = "sha256:ec1ff72739eeaa11b7fc0fef282378066fb30ecb4d58fd8ebc5d5852a9d1cef4"
MAX_INPUT_BYTES = 65536
MAX_OUTPUT_BYTES = 65536
MAX_TIMEOUT_MS = 3000
MAX_RESULTS = 32
MAX_INPUT_DEPTH = 16
MAX_INPUT_NODES = 4096
MAX_RESULT_NODES = 65536
MAX_OBJECT_PROPERTIES = 128
MAX_ARRAY_ITEMS = 256
MAX_KEY_LENGTH = 128
MAX_STRING_LENGTH = 4096
MAX_EVIDENCE_REFS = 32
MAX_EVIDENCE_REF_LENGTH = 128
MAX_GENERATION = 2147483647
REQUEST_ID_RE = re.compile(r"^[!-~]{1,128}$")
ACTIVATION_ID_RE = re.compile(r"^act:[a-f0-9]{32}$")
INVOCATION_ID_RE = re.compile(r"^inv:[a-f0-9]{32}$")
ALLOWED_OPERATIONS = frozenset(
    {
        "parse",
        "inspect_startup",
        "inspect_source_graph",
        "diagnose_quoting",
        "style_check",
        "check_plan",
    }
)
OPERATION_FIELDS: dict[str, tuple[dict[str, object], ...]] = {
    "parse": (
        {"name": "source", "type": "string", "required": True},
        {"name": "path", "type": "string", "required": False},
    ),
    "inspect_startup": (
        {"name": "path", "type": "string", "required": True},
    ),
    "inspect_source_graph": (
        {"name": "path", "type": "string", "required": True},
    ),
    "diagnose_quoting": (
        {"name": "source", "type": "string", "required": True},
        {"name": "path", "type": "string", "required": False},
    ),
    "style_check": (
        {"name": "source", "type": "string", "required": True},
        {"name": "path", "type": "string", "required": False},
    ),
    "check_plan": (
        {"name": "path", "type": "string", "required": True},
    ),
}
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


class BashExpertAdapterError(RuntimeError):
    """Fail-closed adapter error. No shell execution or model fallback is permitted."""


def _source_lock_path() -> Path:
    return Path(__file__).resolve().parents[2] / "expert-source.lock.json"


def _validate_source_lock() -> None:
    try:
        raw = _source_lock_path().read_bytes()
    except OSError as error:
        raise BashExpertAdapterError("source-lock-unavailable") from error
    if "sha256:" + hashlib.sha256(raw).hexdigest() != MANIFEST_DIGEST:
        raise BashExpertAdapterError("source-lock-digest-mismatch")
    try:
        lock = json.loads(raw, parse_constant=_reject_json_constant)
    except (TypeError, UnicodeDecodeError, ValueError) as error:
        raise BashExpertAdapterError("source-lock-invalid") from error
    if type(lock) is not dict:
        raise BashExpertAdapterError("source-lock-invalid")

    canonical = lock.get("canonical_source")
    runtime_contract = lock.get("runtime_contract")
    runtime_repo, runtime_issue = UPSTREAM_CONTRACT.rsplit("#", 1)
    if not (
        type(lock.get("schema_version")) is int
        and lock.get("schema_version") == 1
        and type(lock.get("expert_id")) is str
        and lock.get("expert_id") == EXPERT_ID
        and type(lock.get("adapter_version")) is str
        and lock.get("adapter_version") == PLUGIN_VERSION
        and type(canonical) is dict
        and canonical.get("repository") == "lost-rob0t/dotfiles"
        and canonical.get("path") == SOURCE_REFERENCE.removeprefix("dotfiles:")
        and type(canonical.get("issue")) is int
        and canonical.get("issue") == SOURCE_ISSUE
        and type(canonical.get("commit")) is str
        and re.fullmatch(r"[a-f0-9]{40}", canonical["commit"]) is not None
        and type(runtime_contract) is dict
        and runtime_contract.get("repository") == runtime_repo
        and type(runtime_contract.get("issue")) is int
        and str(runtime_contract.get("issue")) == runtime_issue
    ):
        raise BashExpertAdapterError("source-lock-identity-mismatch")

    try:
        from zara_expert import language_family as language_family_module
    except ImportError:
        return
    try:
        specs = tuple(
            spec
            for spec in language_family_module.language_family_specs()
            if getattr(spec, "key", None) == "bash"
        )
    except Exception as error:
        raise BashExpertAdapterError("source-lock-host-unavailable") from error
    if len(specs) != 1:
        raise BashExpertAdapterError("source-lock-host-mismatch")
    spec = specs[0]
    if not (
        getattr(spec, "expert_id", None) == EXPERT_ID
        and getattr(spec, "source_reference", None) == SOURCE_REFERENCE
        and getattr(spec, "upstream_issue", None) == UPSTREAM_CONTRACT
        and tuple(getattr(spec, "extensions", ())) == LANGUAGE_EXTENSIONS
        and tuple(getattr(spec, "applicability_keywords", ())) == LANGUAGE_KEYWORDS
    ):
        raise BashExpertAdapterError("source-lock-host-mismatch")


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _reject_duplicate_object_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, child in pairs:
        if key in value:
            raise BashExpertAdapterError("ambiguous-input-json")
        value[key] = child
    return value


def _validate_json_tree(value: object) -> None:
    stack: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > MAX_INPUT_NODES or depth > MAX_INPUT_DEPTH:
            raise BashExpertAdapterError("input-structure-too-complex")
        if isinstance(current, dict):
            if len(current) > MAX_OBJECT_PROPERTIES:
                raise BashExpertAdapterError("input-object-too-large")
            for key, child in current.items():
                if not isinstance(key, str) or len(key) > MAX_KEY_LENGTH:
                    raise BashExpertAdapterError("invalid-input-key")
                stack.append((child, depth + 1))
        elif isinstance(current, list):
            if len(current) > MAX_ARRAY_ITEMS:
                raise BashExpertAdapterError("input-array-too-large")
            stack.extend((child, depth + 1) for child in current)
        elif isinstance(current, str):
            if len(current) > MAX_STRING_LENGTH:
                raise BashExpertAdapterError("input-string-too-large")
        elif isinstance(current, float) and not math.isfinite(current):
            raise BashExpertAdapterError("invalid-input-number")
        elif current is not None and not isinstance(current, (str, int, float, bool)):
            raise BashExpertAdapterError("invalid-input-value")


def _validate_request_id(value: str) -> None:
    if type(value) is not str or REQUEST_ID_RE.fullmatch(value) is None:
        raise BashExpertAdapterError("invalid-request-id")


def _validate_activation_id(value: str) -> None:
    if type(value) is not str or ACTIVATION_ID_RE.fullmatch(value) is None:
        raise BashExpertAdapterError("invalid-activation-id")


def _json_integer(value: object, field: str, minimum: int, maximum: int) -> int:
    if type(value) is not int:
        raise BashExpertAdapterError(f"invalid-{field}")
    if not minimum <= value <= maximum:
        raise BashExpertAdapterError(f"invalid-{field}")
    return value


def _validate_generation(value: object, field: str) -> int:
    return _json_integer(value, field, 0, MAX_GENERATION)


def _validate_limit(value: object, field: str, maximum: int) -> int:
    return _json_integer(value, field, 1, maximum)


def _validate_operation_input(operation: str, payload: Mapping[str, object]) -> None:
    declared = {field["name"]: field for field in OPERATION_FIELDS[operation]}
    if set(payload) - set(declared):
        raise BashExpertAdapterError("unknown-operation-input")
    for name, field in declared.items():
        if field["required"] and name not in payload:
            raise BashExpertAdapterError("missing-operation-input")
        if name in payload and field["type"] == "string" and not isinstance(payload[name], str):
            raise BashExpertAdapterError("invalid-operation-input")


def _operation_descriptor(operation: str) -> dict[str, object]:
    return {
        "operation_id": operation,
        "input_schema": {"fields": [dict(field) for field in OPERATION_FIELDS[operation]]},
        "output_schema": {"fields": []},
    }


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
            raise BashExpertAdapterError("invalid-expert-data-json")

        if type(current) is dict:
            container_id = id(current)
            if container_id in active_containers:
                raise BashExpertAdapterError("invalid-expert-data-json")
            active_containers.add(container_id)
            stack.append((True, current))
            for key, child in current.items():
                if type(key) is not str:
                    raise BashExpertAdapterError("invalid-expert-data-json")
                stack.append((False, child))
        elif type(current) is list:
            container_id = id(current)
            if container_id in active_containers:
                raise BashExpertAdapterError("invalid-expert-data-json")
            active_containers.add(container_id)
            stack.append((True, current))
            stack.extend((False, child) for child in current)
        elif type(current) is float:
            if not math.isfinite(current):
                raise BashExpertAdapterError("invalid-expert-data-json")
        elif current is None or type(current) in (str, int, bool):
            continue
        else:
            raise BashExpertAdapterError("invalid-expert-data-json")


def _validate_result_payload(result: Mapping[str, object]) -> tuple[dict[str, object], list[str]]:
    data = result.get("data")
    if type(data) is not dict:
        raise BashExpertAdapterError("invalid-expert-data")
    _validate_result_data_tree(data)

    evidence_refs = result.get("evidence_refs")
    if type(evidence_refs) is not list:
        raise BashExpertAdapterError("invalid-expert-evidence")
    if len(evidence_refs) > MAX_EVIDENCE_REFS:
        raise BashExpertAdapterError("invalid-expert-evidence")
    for evidence_ref in evidence_refs:
        if (
            type(evidence_ref) is not str
            or not evidence_ref
            or len(evidence_ref) > MAX_EVIDENCE_REF_LENGTH
        ):
            raise BashExpertAdapterError("invalid-expert-evidence")
    return data, evidence_refs


def _validate_result_usage(result: Mapping[str, object]) -> None:
    usage = result.get("usage")
    if usage is None:
        raise BashExpertAdapterError("zero-model-proof-missing")
    if type(usage) is not dict:
        raise BashExpertAdapterError("invalid-expert-usage")
    for field in usage:
        if type(field) is not str or field not in USAGE_FIELDS:
            raise BashExpertAdapterError("unknown-expert-usage-field")
    model_calls = usage.get("model_calls")
    if type(model_calls) is not int or model_calls != 0:
        raise BashExpertAdapterError("zero-model-proof-missing")


def _validate_result_metadata(result: Mapping[str, object]) -> None:
    for field in result:
        if type(field) is not str or field not in RESULT_FIELDS:
            raise BashExpertAdapterError("unknown-expert-result-field")

    error_code = result.get("error_code")
    if error_code is not None and (
        type(error_code) is not str or error_code not in RESULT_ERROR_CODES
    ):
        raise BashExpertAdapterError("invalid-expert-error-code")

    error_message = result.get("error_message", "")
    if type(error_message) is not str or len(error_message) > MAX_STRING_LENGTH:
        raise BashExpertAdapterError("invalid-expert-error-message")

    replayed = result.get("replayed", False)
    if type(replayed) is not bool:
        raise BashExpertAdapterError("invalid-expert-replayed")


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
        raise BashExpertAdapterError("invalid-expert-invocation-id")
    expected_identity = {
        "protocol": PROTOCOL,
        "request_id": request_id,
        "activation_id": activation_id,
        "expert_id": EXPERT_ID,
        "expert_version": PLUGIN_VERSION,
        "manifest_digest": MANIFEST_DIGEST,
        "expert_operation": expert_operation,
    }
    for field, expected in expected_identity.items():
        actual = result.get(field)
        if type(actual) is not str or actual != expected:
            raise BashExpertAdapterError("expert-result-identity-mismatch")
    resolved_registry_generation = result.get("resolved_registry_generation")
    if (
        type(resolved_registry_generation) is not int
        or resolved_registry_generation != registry_generation
    ):
        raise BashExpertAdapterError("stale-expert-result")
    resolved_runtime_generation = result.get("resolved_runtime_generation")
    if (
        type(resolved_runtime_generation) is not int
        or resolved_runtime_generation != runtime_generation
    ):
        raise BashExpertAdapterError("stale-expert-result")
    verdict = result.get("verdict")
    if type(verdict) is not str or verdict not in RESULT_VERDICTS:
        raise BashExpertAdapterError("invalid-expert-verdict")
    data, evidence_refs = _validate_result_payload(result)
    _validate_result_usage(result)
    receipts = result.get("effect_receipts")
    if type(receipts) is not list:
        raise BashExpertAdapterError("read-only-effect-proof-missing")
    if receipts:
        raise BashExpertAdapterError("read-only-effect-leak")
    if verdict == "cancelled":
        if data or evidence_refs:
            raise BashExpertAdapterError("cancelled-expert-output-leak")


class ZaraBashExpertPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-bash-expert",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Pure-symbolic BashExpert adapter over the canonical Zara expert host",
    )

    def __init__(self) -> None:
        self._runtime: Any | None = None

    def start(self, runtime) -> None:
        # Binding is intentionally passive: discovery/start performs no source,
        # shell process, network access, expert activation, or model call.
        self._runtime = runtime
        return None

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
            raise BashExpertAdapterError("input-must-be-json-text")
        if len(input_json.encode("utf-8")) > MAX_INPUT_BYTES:
            raise BashExpertAdapterError("input-too-large")
        try:
            value = json.loads(
                input_json,
                parse_constant=_reject_json_constant,
                object_pairs_hook=_reject_duplicate_object_pairs,
            )
        except (TypeError, ValueError) as error:
            raise BashExpertAdapterError("invalid-input-json") from error
        if not isinstance(value, dict):
            raise BashExpertAdapterError("input-must-be-object")
        _validate_json_tree(value)
        return value

    def descriptor(self) -> str:
        _validate_source_lock()
        return self._json(
            {
                "protocol": PROTOCOL,
                "expert_id": EXPERT_ID,
                "expert_version": PLUGIN_VERSION,
                "package_namespace": "zara-bash-expert",
                "manifest_digest": MANIFEST_DIGEST,
                "name": "BashExpert",
                "description": "Deterministic Bash parse, startup, source-graph, quoting, and style inspection.",
                "source_reference": SOURCE_REFERENCE,
                "reasoning_kind": "symbolic",
                "operations": [
                    _operation_descriptor(operation)
                    for operation in sorted(ALLOWED_OPERATIONS)
                ],
                "applicability": {"keywords": list(LANGUAGE_KEYWORDS)},
                "required_capabilities": [HOST_CAPABILITY],
                "possible_effects": ["none"],
                "supported_engines": ["swipl"],
                "supported_platforms": ["desktop", "server"],
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
        timeout_ms: int = MAX_TIMEOUT_MS,
        max_results: int = MAX_RESULTS,
        max_output_bytes: int = MAX_OUTPUT_BYTES,
    ) -> str:
        _validate_source_lock()
        if type(expert_operation) is not str or expert_operation not in ALLOWED_OPERATIONS:
            raise BashExpertAdapterError("unsupported-expert-operation")
        _validate_request_id(request_id)
        _validate_activation_id(activation_id)
        registry_generation = _validate_generation(
            expected_registry_generation, "registry-generation"
        )
        runtime_generation = _validate_generation(
            expected_runtime_generation, "runtime-generation"
        )
        timeout = _validate_limit(timeout_ms, "timeout-ms", MAX_TIMEOUT_MS)
        results_limit = _validate_limit(max_results, "max-results", MAX_RESULTS)
        output_limit = _validate_limit(
            max_output_bytes, "max-output-bytes", MAX_OUTPUT_BYTES
        )

        payload = self._decode_input(input_json)
        _validate_operation_input(expert_operation, payload)
        runtime = self._runtime
        resolver = getattr(runtime, "resolve_capability", None)
        invoker = getattr(runtime, "invoke_capability", None)
        if not callable(resolver) or not callable(invoker):
            raise BashExpertAdapterError("expert-host-composition-unavailable")

        try:
            handle = resolver(HOST_CAPABILITY)
            result = invoker(
                handle,
                {
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
                        "timeout_ms": timeout,
                        "max_results": results_limit,
                        "max_output_bytes": output_limit,
                        "max_model_calls": 0,
                    },
                },
            )
        except BashExpertAdapterError:
            raise
        except Exception as error:
            raise BashExpertAdapterError("expert-host-invocation-failed") from error

        if type(result) is not dict:
            raise BashExpertAdapterError("invalid-expert-result")
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
            raise BashExpertAdapterError("invalid-expert-result-json") from error
        if len(encoded.encode("utf-8")) > output_limit:
            raise BashExpertAdapterError("expert-result-too-large")
        if type(snapshot) is not dict:
            raise BashExpertAdapterError("invalid-expert-result")
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
        # Core ZARA-EXPERT/1 owns descriptor publication and invocation. Keep the
        # lower-level class inert too: direct module imports must not resurrect a
        # parallel tool namespace that bypasses activation/generation/budget fences.
        return ()


def create_plugin():
    return ZaraBashExpertPlugin()
