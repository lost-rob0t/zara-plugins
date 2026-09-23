from __future__ import annotations

from typing import Any

from . import lisp_output_contract as _output
from .composition import InvocationResult


_AUTHORITY_FIELDS = ("effect_receipt", "postcondition_evidence")
_REPAIR_OPERATIONS = frozenset({"repair.verify", "repair.apply"})


def install_lisp_authority_snapshot_fence() -> None:
    """Detach nested verified authority metadata before public projection.

    The existing Lisp output contract validates effect and fresh-postcondition
    authority, then snapshots their top-level dictionaries. Nested metadata can
    still be Core-owned mutable state, so reuse the same recursive symbolic
    snapshot primitive after validation. This changes ownership only: Zara Core
    remains the effect/receipt/postcondition authority and Prolog-RLM remains the
    Lisp parser/repair semantic authority.
    """

    if getattr(_output, "_LISP_AUTHORITY_SNAPSHOT_FENCE_INSTALLED", False):
        return

    original_snapshot = _output._snapshot_authority_projection

    def deep_snapshot(operation: str, result: InvocationResult) -> InvocationResult:
        projected = original_snapshot(operation, result)
        if operation not in _REPAIR_OPERATIONS:
            return projected

        data = dict(projected.data)
        for field in _AUTHORITY_FIELDS:
            value: Any = data.get(field)
            if type(value) is dict:
                data[field] = _output._snapshot_symbolic_value(value)

        return InvocationResult(
            status=projected.status,
            data=data,
            evidence=projected.evidence,
            delegations=projected.delegations,
            explanation=projected.explanation,
            model_calls=projected.model_calls,
        )

    _output._snapshot_authority_projection = deep_snapshot
    _output._LISP_AUTHORITY_SNAPSHOT_FENCE_INSTALLED = True


__all__ = ["install_lisp_authority_snapshot_fence"]
