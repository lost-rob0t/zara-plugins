from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import lisp_evidence_fence as _evidence
from .composition import CompositionError


def _guard_data_evidence_refs(data: Any) -> None:
    """Fence public data evidence identities before canonical validation.

    The existing Lisp output contract owns evidence grammar. This guard only
    keeps `data.evidence_refs` on canonical built-in sequence/string identities
    so Python subclasses cannot forge equality with an accepted reference before
    durable/public projection. It does not add parser, provider, tool, or receipt
    semantics.
    """

    if not isinstance(data, Mapping):
        return
    references = data.get("evidence_refs", ())
    if isinstance(references, (str, bytes)) or not isinstance(
        references, (list, tuple)
    ):
        return
    if type(references) not in (list, tuple):
        raise CompositionError(
            "Lisp expert data.evidence_refs must be a built-in list or tuple"
        )
    if any(type(reference) is not str for reference in references):
        raise CompositionError(
            "Lisp expert data.evidence_refs must contain strings"
        )


def install_lisp_data_evidence_type_fence() -> None:
    """Extend the existing pre-normalization Lisp evidence identity fence."""

    if getattr(_evidence, "_LISP_DATA_EVIDENCE_TYPE_FENCE_INSTALLED", False):
        return

    original_handler_guard = _evidence._guard_handler_outcome
    original_core_guard = _evidence._guard_core_outcome

    def guarded_handler(outcome: Any) -> None:
        original_handler_guard(outcome)
        if isinstance(outcome, Mapping):
            _guard_data_evidence_refs(outcome.get("data"))

    def guarded_core(outcome: Any) -> None:
        original_core_guard(outcome)
        _guard_data_evidence_refs(getattr(outcome, "data", None))

    _evidence._guard_handler_outcome = guarded_handler
    _evidence._guard_core_outcome = guarded_core
    _evidence._LISP_DATA_EVIDENCE_TYPE_FENCE_INSTALLED = True


__all__ = ["install_lisp_data_evidence_type_fence"]
