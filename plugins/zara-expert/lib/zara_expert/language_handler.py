from __future__ import annotations

from typing import Any

from .domain import ExpertError, ExpertHost
from .language_family import MAX_MODEL_CALLS, invoke_language_operation, language_family_specs


_EXPERT_IDS = frozenset(spec.expert_id for spec in language_family_specs())
_EXPERT_KEYS = frozenset(spec.key for spec in language_family_specs())


def _canonical_expert_id(expert_id: str) -> str:
    if expert_id in _EXPERT_IDS:
        return expert_id
    if expert_id in _EXPERT_KEYS:
        return f"zara:expert/{expert_id}"
    raise ExpertError(f"unknown language expert: {expert_id!r}")


def make_language_expert_handler(host: ExpertHost, expert_id: str):
    """Return a Core-owned ZARA-EXPERT/1 handler for one language expert.

    The selected operation is trusted host metadata supplied by Zara Core, not
    caller data. Pure-symbolic outcomes always expose an exact zero model-call
    ledger. Filesystem repair remains outside this adapter and must cross Zara's
    typed effect/approval path before fresh postcondition verification.
    """

    canonical_id = _canonical_expert_id(expert_id)

    def handler(
        *,
        expert_operation: str,
        arguments: list[Any] | None = None,
        repair: dict[str, Any] | None = None,
        expected_preimage: str | None = None,
        source_generation: str | None = None,
    ) -> dict[str, Any]:
        if expert_operation == "repair.apply":
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

        if repair is not None or expected_preimage is not None or source_generation is not None:
            raise ExpertError(
                "repair effect fields are accepted only for repair.apply through Zara Core"
            )

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
