from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import lisp_composition as _base
from .composition import CompositionError


_RECEIPT_AUTHORITY_STRING_FIELDS = frozenset(
    {
        "receipt_id",
        "capability",
        "source_generation",
    }
)


def _guard_receipt_object(receipt: Mapping[Any, Any], label: str) -> None:
    """Reject custom mapping/scalar semantics at the Core receipt boundary.

    The canonical Core validator owns receipt schema and lineage rules. This
    guard only prevents Python mapping/scalar objects from overriding lookup,
    iteration, hashing, or equality while those existing rules compare the
    canonical effect receipt with its projected copy and source generation.
    """

    if type(receipt) is not dict:
        raise CompositionError(f"{label} must be a built-in dict")

    for key, value in receipt.items():
        if isinstance(key, str) and type(key) is not str:
            raise CompositionError(f"{label} keys must be built-in strings")
        if isinstance(value, str) and type(value) is not str:
            raise CompositionError(f"{label} string values must be built-in strings")

    # These fields participate directly in receipt identity/authority lineage.
    # Do not let an arbitrary non-string object provide forged equality at the
    # canonical-vs-projected receipt or request-generation comparisons. Presence
    # and full schema remain Core-owned; this fence only narrows host scalar type.
    for field in _RECEIPT_AUTHORITY_STRING_FIELDS:
        if field in receipt and type(receipt[field]) is not str:
            raise CompositionError(
                f"{label} {field} must be a built-in string"
            )


def _guard_core_effect_receipts(outcome: Any) -> None:
    """Reject custom receipt wire semantics before Core result projection.

    Zara Core remains the sole effect and receipt authority. This fence only
    preserves canonical host-language wire identity for containers/scalars that
    the existing Lisp composition validator already accepts. Ordinary malformed
    values are left to that validator so schema/error ownership is unchanged.
    """

    receipts = getattr(outcome, "effect_receipts", None)
    if not isinstance(receipts, (list, tuple)):
        return
    if type(receipts) not in (list, tuple):
        raise CompositionError(
            "Core Lisp expert effect_receipts must be a built-in list or tuple"
        )

    for receipt in receipts:
        if isinstance(receipt, Mapping):
            _guard_receipt_object(receipt, "Core Lisp expert effect receipt")

    # `data` has its own canonical mapping fence. Only inspect it here after it
    # is already a built-in dict so this receipt fence never invokes arbitrary
    # custom Mapping.get/item behavior ahead of that existing validation.
    data = getattr(outcome, "data", None)
    if type(data) is not dict:
        return
    projected_receipt = data.get("effect_receipt")
    if isinstance(projected_receipt, Mapping):
        _guard_receipt_object(
            projected_receipt,
            "Core Lisp expert projected effect receipt",
        )


def install_lisp_effect_receipt_type_fence() -> None:
    """Layer a narrow receipt wire-type fence onto the existing Core adapter."""

    if getattr(_base, "_LISP_EFFECT_RECEIPT_TYPE_FENCE_INSTALLED", False):
        return

    original_core = _base._validated_core_result

    def fenced_core(
        expert_id: str,
        operation: str,
        input_data: Mapping[str, Any],
        outcome: Any,
    ):
        _guard_core_effect_receipts(outcome)
        return original_core(expert_id, operation, input_data, outcome)

    _base._validated_core_result = fenced_core
    _base._LISP_EFFECT_RECEIPT_TYPE_FENCE_INSTALLED = True


__all__ = ["install_lisp_effect_receipt_type_fence"]
