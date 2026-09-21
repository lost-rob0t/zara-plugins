from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .plugin import (
    MAX_GENERATION,
    MAX_OUTPUT_BYTES,
    MAX_RESULTS,
    MAX_TIMEOUT_MS,
    OPERATION_FIELDS,
    BashExpertAdapterError,
    ZaraBashExpertPlugin,
)


_FIELD_TYPES: dict[str, type[object]] = {
    "string": str,
}


def _validate_expected_generation(value: object, field: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_GENERATION:
        raise BashExpertAdapterError(f"invalid-{field}")
    return value


def _validate_operation_payload(operation: str, payload: Mapping[str, Any]) -> None:
    if type(operation) is not str:
        raise BashExpertAdapterError("unsupported-expert-operation")
    fields = OPERATION_FIELDS.get(operation)
    if fields is None:
        raise BashExpertAdapterError("unsupported-expert-operation")

    schema = {str(field["name"]): field for field in fields}
    unexpected = sorted(set(payload) - set(schema))
    if unexpected:
        raise BashExpertAdapterError("unexpected-input-field")

    for name, field in schema.items():
        if field.get("required") is True and name not in payload:
            raise BashExpertAdapterError("missing-required-input-field")
        if name not in payload:
            continue
        field_type = field.get("type")
        expected_type = _FIELD_TYPES.get(str(field_type))
        if expected_type is None:
            raise BashExpertAdapterError("unsupported-input-field-type")
        value = payload[name]
        if not isinstance(value, expected_type):
            raise BashExpertAdapterError("invalid-input-field-type")
        if name == "path" and (not value or "\x00" in value):
            raise BashExpertAdapterError("invalid-input-path")


class ZaraBashExpertBoundaryPlugin(ZaraBashExpertPlugin):
    """Typed ZARA-EXPERT/1 admission boundary for BashExpert operations."""

    def invoke(
        self,
        request_id: str,
        activation_id: str,
        expert_operation: str,
        expected_registry_generation: int,
        expected_runtime_generation: int,
        input_json: str = "{}",
        timeout_ms: int | float = MAX_TIMEOUT_MS,
        max_results: int | float = MAX_RESULTS,
        max_output_bytes: int | float = MAX_OUTPUT_BYTES,
    ) -> str:
        registry_generation = _validate_expected_generation(
            expected_registry_generation, "registry-generation"
        )
        runtime_generation = _validate_expected_generation(
            expected_runtime_generation, "runtime-generation"
        )
        payload = self._decode_input(input_json)
        _validate_operation_payload(expert_operation, payload)
        return super().invoke(
            request_id,
            activation_id,
            expert_operation,
            registry_generation,
            runtime_generation,
            input_json,
            timeout_ms,
            max_results,
            max_output_bytes,
        )

    def tools(self):
        # BashExpert discovery/invocation is owned by canonical ZARA-EXPERT/1.
        # Publishing adapter-local descriptor/invoke StructuredTools would let
        # callers bypass Core activation, cancellation, generation and shared
        # budget fencing, so the public plugin surface intentionally exposes no
        # parallel expert tool namespace.
        return ()


def create_plugin() -> ZaraBashExpertBoundaryPlugin:
    return ZaraBashExpertBoundaryPlugin()
