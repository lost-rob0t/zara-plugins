from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import lisp_evidence_fence as _evidence
from .composition import CompositionError


def _guard_usage_ledger(value: Any, label: str) -> None:
    """Keep zero-model accounting on canonical host-language wire types.

    Existing Lisp composition owns the usage schema and exact ``model_calls == 0``
    rule. This fence only rejects Mapping/string-key subclasses before that rule
    reads the ledger, so host-controlled lookup/equality behavior cannot widen the
    pure-symbolic accounting boundary.
    """

    if not isinstance(value, Mapping):
        return
    if type(value) is not dict:
        raise CompositionError(f"{label} must be a built-in dict")
    if any(type(key) is not str for key in value):
        raise CompositionError(f"{label} keys must be built-in strings")


def _guard_handler_outcome(outcome: Any) -> None:
    if not isinstance(outcome, Mapping):
        return
    _guard_usage_ledger(outcome.get("usage"), "Lisp expert usage ledger")


def _guard_core_outcome(outcome: Any) -> None:
    _guard_usage_ledger(
        getattr(outcome, "usage", None),
        "Core Lisp expert usage ledger",
    )


def install_lisp_usage_ledger_type_fence() -> None:
    """Layer a narrow usage-ledger wire fence onto existing Lisp composition."""

    if getattr(_evidence, "_LISP_USAGE_LEDGER_TYPE_FENCE_INSTALLED", False):
        return

    original_handler_guard = _evidence._guard_handler_outcome
    original_core_guard = _evidence._guard_core_outcome

    def guarded_handler(outcome: Any) -> None:
        original_handler_guard(outcome)
        _guard_handler_outcome(outcome)

    def guarded_core(outcome: Any) -> None:
        original_core_guard(outcome)
        _guard_core_outcome(outcome)

    _evidence._guard_handler_outcome = guarded_handler
    _evidence._guard_core_outcome = guarded_core
    _evidence._LISP_USAGE_LEDGER_TYPE_FENCE_INSTALLED = True


__all__ = ["install_lisp_usage_ledger_type_fence"]
