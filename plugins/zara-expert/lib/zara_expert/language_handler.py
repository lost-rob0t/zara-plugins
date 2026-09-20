from __future__ import annotations

from typing import Any

from .domain import ExpertError, ExpertHost
from .language_family import (
    MAX_MODEL_CALLS,
    invoke_language_operation,
    language_expert_schemas,
    language_family_specs,
)


_EXPERT_IDS = frozenset(spec.expert_id for spec in language_family_specs())
_EXPERT_KEYS = frozenset(spec.key for spec in language_family_specs())
_RESULT_VARIABLE = {"var": "Result"}


def _canonical_expert_id(expert_id: str) -> str:
    if expert_id in _EXPERT_IDS:
        return expert_id
    if expert_id in _EXPERT_KEYS:
        return f"zara:expert/{expert_id}"
    raise ExpertError(f"unknown language expert: {expert_id!r}")


def _operation_arguments(expert_operation: str, payload: dict[str, Any]) -> list[Any]:
    schemas = language_expert_schemas()
    schema = schemas.get(expert_operation)
    if schema is None:
        raise ExpertError(f"unsupported language expert operation: {expert_operation!r}")

    fields = schema["input_schema"]["fields"]
    allowed = {field["name"] for field in fields}
    unknown = set(payload) - allowed
    if unknown:
        raise ExpertError(
            f"unknown input field for {expert_operation!r}: {sorted(unknown)[0]!r}"
        )
    missing = [
        field["name"]
        for field in fields
        if field["required"] and field["name"] not in payload
    ]
    if missing:
        raise ExpertError(
            f"missing required input field for {expert_operation!r}: {missing[0]!r}"
        )

    # Registered language predicates reserve their final argument for this
    # adapter-created result variable. User payloads are inert ground values and
    # can never manufacture Prolog variable authority.
    return [payload.get(field["name"]) for field in fields] + [dict(_RESULT_VARIABLE)]


def make_language_expert_handler(host: ExpertHost, expert_id: str):
    """Return a Core-owned ZARA-EXPERT/1 handler for one language expert.

    ``expert_operation`` is trusted host metadata injected by Zara Core. The
    remaining keyword payload is validated against the selected descriptor
    schema, converted to the registered-predicate ABI, and dispatched through
    the existing ExpertHost capability boundary. Pure-symbolic outcomes always
    expose an exact zero model-call ledger. Filesystem repair remains outside
    this adapter and must cross Zara's typed effect/approval path before fresh
    postcondition verification.
    """

    canonical_id = _canonical_expert_id(expert_id)

    def handler(*, expert_operation: str, **payload: Any) -> dict[str, Any]:
        if expert_operation == "repair.apply":
            # Core validates the public repair.apply schema before dispatch. The
            # plugin still refuses to write: actual mutation must cross Zara's
            # typed capability/approval/effect path and then fresh verification.
            return {
                "verdict": "blocked",
                "data": {
                    "reason": "canonical-typed-edit-required",
                    "expert_id": canonical_id,
                },
                "evidence_refs": [],
                "usage": {"model_calls": MAX_MODEL_CALLS},
                "effect_receipts": [],
            }

        arguments = _operation_arguments(expert_operation, payload)
        result = invoke_language_operation(
            host,
            canonical_id,
            expert_operation,
            arguments,
        )
        return {
            "verdict": "succeeded",
            "data": {"result": result},
            "evidence_refs": [],
            "usage": {"model_calls": MAX_MODEL_CALLS},
            "effect_receipts": [],
        }

    return handler


__all__ = ["make_language_expert_handler"]
