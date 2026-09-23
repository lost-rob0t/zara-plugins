from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import lisp_evidence_fence as _evidence
from .composition import CompositionError


def _require_builtin_verdict(value: Any, label: str) -> None:
    """Reject host-controlled string identity before verdict semantics.

    The existing Lisp composition/output contract owns the accepted verdict
    semantics. This guard only prevents a Python ``str`` subclass from
    overriding equality at cancellation/success checks or surviving into the
    durable/public InvocationResult. Non-string shape errors remain owned by the
    existing validators.
    """

    if isinstance(value, str) and type(value) is not str:
        raise CompositionError(f"{label} must be a built-in string")


def _guard_handler_verdict(outcome: Any) -> None:
    if not isinstance(outcome, Mapping):
        return
    _require_builtin_verdict(outcome.get("verdict"), "Lisp expert verdict")


def _guard_core_verdict(outcome: Any) -> None:
    verdict = getattr(outcome, "verdict", None)
    status = getattr(verdict, "value", verdict)
    _require_builtin_verdict(status, "Core Lisp expert verdict")


def install_lisp_verdict_type_fence() -> None:
    """Extend the existing pre-normalization Lisp host/wire identity fence."""

    if getattr(_evidence, "_LISP_VERDICT_TYPE_FENCE_INSTALLED", False):
        return

    original_handler_guard = _evidence._guard_handler_outcome
    original_core_guard = _evidence._guard_core_outcome

    def guarded_handler(outcome: Any) -> None:
        original_handler_guard(outcome)
        _guard_handler_verdict(outcome)

    def guarded_core(outcome: Any) -> None:
        original_core_guard(outcome)
        _guard_core_verdict(outcome)

    _evidence._guard_handler_outcome = guarded_handler
    _evidence._guard_core_outcome = guarded_core
    _evidence._LISP_VERDICT_TYPE_FENCE_INSTALLED = True


__all__ = ["install_lisp_verdict_type_fence"]
