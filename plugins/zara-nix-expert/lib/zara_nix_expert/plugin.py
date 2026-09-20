from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from typing import Any

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin


PLUGIN_VERSION = "0.1.0"
PROTOCOL = "ZARA-EXPERT/1"
EXPERT_ID = "zara:expert/nix"
HOST_CAPABILITY = "expert.invoke"
MANIFEST_DIGEST = "sha256:79ed16fd0c6100baefdd6ce562296ef99d9dc51fb7f90935888f9860ccb6e140"
MAX_INPUT_BYTES = 65536
MAX_OUTPUT_BYTES = 65536
MAX_TIMEOUT_MS = 3000
MAX_RESULTS = 32
MAX_INPUT_DEPTH = 16
MAX_INPUT_NODES = 4096
MAX_OBJECT_PROPERTIES = 128
MAX_ARRAY_ITEMS = 256
MAX_KEY_LENGTH = 128
MAX_STRING_LENGTH = 4096
MAX_GENERATION = 9007199254740991
REFERENCE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
ALLOWED_OPERATIONS = frozenset(
    {
        "parse",
        "inspect_flake",
        "inspect_module",
        "inspect_home_manager",
        "style_check",
        "check_plan",
    }
)
OPERATION_SCHEMAS = {
    "parse": ("schema:nix-expert-parse-input-v1", "schema:nix-expert-result-v1"),
    "inspect_flake": (
        "schema:nix-expert-inspect-flake-input-v1",
        "schema:nix-expert-result-v1",
    ),
    "inspect_module": (
        "schema:nix-expert-inspect-module-input-v1",
        "schema:nix-expert-result-v1",
    ),
    "inspect_home_manager": (
        "schema:nix-expert-inspect-home-manager-input-v1",
        "schema:nix-expert-result-v1",
    ),
    "style_check": (
        "schema:nix-expert-style-check-input-v1",
        "schema:nix-expert-result-v1",
    ),
    "check_plan": (
        "schema:nix-expert-check-plan-input-v1",
        "schema:nix-expert-result-v1",
    ),
}


class NixExpertAdapterError(RuntimeError):
    """Fail-closed adapter error. No provider/model fallback is permitted."""


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _validate_json_tree(value: object) -> None:
    stack: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > MAX_INPUT_NODES or depth > MAX_INPUT_DEPTH:
            raise NixExpertAdapterError("input-structure-too-complex")
        if isinstance(current, dict):
            if len(current) > MAX_OBJECT_PROPERTIES:
                raise NixExpertAdapterError("input-object-too-large")
            for key, child in current.items():
                if not isinstance(key, str) or len(key) > MAX_KEY_LENGTH:
                    raise NixExpertAdapterError("invalid-input-key")
                stack.append((child, depth + 1))
        elif isinstance(current, list):
            if len(current) > MAX_ARRAY_ITEMS:
                raise NixExpertAdapterError("input-array-too-large")
            stack.extend((child, depth + 1) for child in current)
        elif isinstance(current, str):
            if len(current) > MAX_STRING_LENGTH:
                raise NixExpertAdapterError("input-string-too-large")
        elif isinstance(current, float) and not math.isfinite(current):
            raise NixExpertAdapterError("invalid-input-number")
        elif current is not None and not isinstance(current, (str, int, float, bool)):
            raise NixExpertAdapterError("invalid-input-value")


def _validate_reference(value: str, field: str) -> None:
    if not isinstance(value, str) or REFERENCE_RE.fullmatch(value) is None:
        raise NixExpertAdapterError(f"invalid-{field}")


def _validate_generation(value: int, field: str) -> None:
    if type(value) is not int or not 1 <= value <= MAX_GENERATION:
        raise NixExpertAdapterError(f"invalid-{field}")


def _validate_limit(value: int, field: str, maximum: int) -> None:
    if type(value) is not int or not 1 <= value <= maximum:
        raise NixExpertAdapterError(f"invalid-{field}")


def _operation_descriptor(operation: str) -> dict[str, object]:
    input_schema, output_schema = OPERATION_SCHEMAS[operation]
    return {
        "id": operation,
        "input_schema": input_schema,
        "output_schema": output_schema,
        "effects": [],
        "required_capabilities": [HOST_CAPABILITY],
    }


class ZaraNixExpertPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-nix-expert",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Pure-symbolic NixExpert adapter over the canonical Zara expert host",
    )

    def __init__(self) -> None:
        self._runtime: Any | None = None

    def start(self, runtime) -> None:
        # Binding is intentionally passive: discovery/start performs no expert
        # activation, Nix evaluation, process execution, network I/O, or model call.
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
            raise NixExpertAdapterError("input-must-be-json-text")
        if len(input_json.encode("utf-8")) > MAX_INPUT_BYTES:
            raise NixExpertAdapterError("input-too-large")
        try:
            value = json.loads(input_json, parse_constant=_reject_json_constant)
        except (TypeError, ValueError) as error:
            raise NixExpertAdapterError("invalid-input-json") from error
        if not isinstance(value, dict):
            raise NixExpertAdapterError("input-must-be-object")
        _validate_json_tree(value)
        return value

    def descriptor(self) -> str:
        return self._json(
            {
                "protocol": PROTOCOL,
                "expert_id": EXPERT_ID,
                "expert_version": PLUGIN_VERSION,
                "package_namespace": "zara-nix-expert",
                "manifest_digest": MANIFEST_DIGEST,
                "name": "NixExpert",
                "description": "Deterministic Nix, flake, module, and Home Manager inspection.",
                "source_reference": "source:dotfiles-nix-expert-v1",
                "reasoning_kind": "symbolic",
                "operations": [
                    _operation_descriptor(operation)
                    for operation in sorted(ALLOWED_OPERATIONS)
                ],
                "applicability_schema": "schema:nix-expert-applicability-v1",
                "required_observations": [],
                "required_capabilities": [HOST_CAPABILITY],
                "possible_effects": [
                    "nix.eval",
                    "nix.check",
                    "nix.build",
                    "home-manager.switch",
                ],
                "supported_engines": ["swi-prolog"],
                "supported_platforms": ["desktop", "server"],
                "placement": {
                    "node_id": "local",
                    "runtime_id": "zara-python",
                },
                "fallback_policy": "none",
                "delegation_policy": "none",
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
        if expert_operation not in ALLOWED_OPERATIONS:
            raise NixExpertAdapterError("unsupported-expert-operation")
        _validate_reference(request_id, "request-id")
        _validate_reference(activation_id, "activation-id")
        _validate_generation(expected_registry_generation, "registry-generation")
        _validate_generation(expected_runtime_generation, "runtime-generation")
        _validate_limit(timeout_ms, "timeout-ms", MAX_TIMEOUT_MS)
        _validate_limit(max_results, "max-results", MAX_RESULTS)
        _validate_limit(max_output_bytes, "max-output-bytes", MAX_OUTPUT_BYTES)

        payload = self._decode_input(input_json)
        runtime = self._runtime
        resolver = getattr(runtime, "resolve_capability", None)
        invoker = getattr(runtime, "invoke_capability", None)
        if not callable(resolver) or not callable(invoker):
            raise NixExpertAdapterError("expert-host-composition-unavailable")

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
                    "expected_registry_generation": expected_registry_generation,
                    "expected_runtime_generation": expected_runtime_generation,
                    "input": payload,
                    "limits": {
                        "timeout_ms": timeout_ms,
                        "max_results": max_results,
                        "max_output_bytes": max_output_bytes,
                        "max_model_calls": 0,
                    },
                },
            )
        except NixExpertAdapterError:
            raise
        except Exception as error:
            raise NixExpertAdapterError("expert-host-invocation-failed") from error

        if not isinstance(result, Mapping):
            raise NixExpertAdapterError("invalid-expert-result")
        usage = result.get("usage")
        model_calls = usage.get("model_calls") if isinstance(usage, Mapping) else None
        if type(model_calls) is not int or model_calls != 0:
            raise NixExpertAdapterError("zero-model-proof-missing")
        receipts = result.get("side_effect_receipts")
        if not isinstance(receipts, list) or receipts:
            raise NixExpertAdapterError("read-only-effect-leak")

        encoded = self._json(dict(result))
        if len(encoded.encode("utf-8")) > max_output_bytes:
            raise NixExpertAdapterError("expert-result-too-large")
        return encoded

    def tools(self):
        return (
            StructuredTool.from_function(
                func=self.descriptor,
                name="nix.expert.descriptor",
                description="Return the bounded ZARA-EXPERT/1 NixExpert descriptor without activating or executing it.",
            ),
            StructuredTool.from_function(
                func=self.invoke,
                name="nix.expert.invoke",
                description="Invoke one allowlisted read-only NixExpert symbolic operation through the canonical expert host with max_model_calls=0.",
            ),
        )


def create_plugin():
    return ZaraNixExpertPlugin()
