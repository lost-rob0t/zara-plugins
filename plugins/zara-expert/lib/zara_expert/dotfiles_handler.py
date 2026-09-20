from __future__ import annotations

import hashlib
from typing import Any

from .domain import ExpertError, ExpertHost
from .dotfiles_family import (
    EXPERT_ID,
    MAX_MODEL_CALLS,
    invoke_dotfiles_operation,
)


_MAX_CORE_EVIDENCE_REFS = 32


def _evidence_refs(result: dict[str, Any]) -> list[str]:
    raw = result.get("evidence", ())
    if isinstance(raw, (str, bytes)) or not isinstance(raw, (list, tuple)):
        raise ExpertError("DotfilesExpert evidence must be a sequence")
    if len(raw) > _MAX_CORE_EVIDENCE_REFS:
        raise ExpertError(
            f"DotfilesExpert evidence exceeds {_MAX_CORE_EVIDENCE_REFS} entries"
        )
    refs: list[str] = []
    for item in raw:
        encoded = str(item).encode("utf-8", errors="strict")
        digest = hashlib.sha256(encoded).hexdigest()
        refs.append(f"evidence:dotfiles:sha256:{digest}")
    return refs


def make_dotfiles_expert_handler(host: ExpertHost):
    """Return the canonical zero-model Core handler for DotfilesExpert."""

    def handler(*, expert_operation: str, **payload: Any) -> dict[str, Any]:
        if expert_operation == "repair.apply":
            return {
                "verdict": "blocked",
                "data": {
                    "reason": "canonical-typed-edit-required",
                    "expert_id": EXPERT_ID,
                },
                "evidence_refs": [],
                "usage": {"model_calls": MAX_MODEL_CALLS},
                "effect_receipts": [],
            }

        result = invoke_dotfiles_operation(host, expert_operation, payload)
        return {
            "verdict": result["verdict"],
            "data": {"result": result},
            "evidence_refs": _evidence_refs(result),
            "usage": {"model_calls": MAX_MODEL_CALLS},
            "effect_receipts": [],
        }

    return handler


__all__ = ["make_dotfiles_expert_handler"]
