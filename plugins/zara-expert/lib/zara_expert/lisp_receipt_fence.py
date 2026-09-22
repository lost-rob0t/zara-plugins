from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import lisp_composition as _base
from .composition import CompositionError


def _guard_core_effect_receipts(outcome: Any) -> None:
    """Reject custom receipt container semantics before Core result projection.

    Zara Core remains the sole effect and receipt authority. This fence only
    preserves the canonical host-language wire identity for receipt containers
    that the existing Lisp composition validator already accepts. Ordinary
    malformed values are left to that validator so error ownership is unchanged.
    """

    receipts = getattr(outcome, "effect_receipts", None)
    if not isinstance(receipts, (list, tuple)):
        return
    if type(receipts) not in (list, tuple):
        raise CompositionError(
            "Core Lisp expert effect_receipts must be a built-in list or tuple"
        )

    for receipt in receipts:
        if isinstance(receipt, Mapping) and type(receipt) is not dict:
            raise CompositionError(
                "Core Lisp expert effect receipt must be a built-in dict"
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
