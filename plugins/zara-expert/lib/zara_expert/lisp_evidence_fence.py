from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import lisp_composition as _base
from .composition import CompositionError


def _require_string_references(value: Any, label: str) -> None:
    """Reject object-to-string authority widening before base normalization.

    The canonical Lisp output contract decides which *strings* are admissible
    evidence references. This guard only preserves that type boundary; it does
    not define evidence grammar, parser semantics, or receipt authority.
    """

    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        return
    if any(not isinstance(item, str) for item in value):
        raise CompositionError(f"{label} must contain strings")


def _guard_handler_outcome(outcome: Any) -> None:
    if not isinstance(outcome, Mapping):
        return

    evidence_refs = outcome.get("evidence_refs", ())
    _require_string_references(evidence_refs, "Lisp expert evidence_refs")
    if evidence_refs:
        return

    data = outcome.get("data")
    if not isinstance(data, Mapping):
        return
    nested = data.get("result")
    if not isinstance(nested, Mapping):
        return
    _require_string_references(nested.get("trace", ()), "Lisp expert host trace")


def _guard_core_outcome(outcome: Any) -> None:
    evidence_refs = getattr(outcome, "evidence_refs", None)
    _require_string_references(evidence_refs, "Core Lisp expert evidence_refs")
    if evidence_refs:
        return

    data = getattr(outcome, "data", None)
    if not isinstance(data, Mapping):
        return
    nested = data.get("result")
    if not isinstance(nested, Mapping):
        return
    _require_string_references(nested.get("trace", ()), "Core Lisp expert host trace")


def install_lisp_evidence_type_fence() -> None:
    """Install a narrow pre-normalization type fence on the existing adapter.

    `lisp_composition` historically normalizes evidence with `str(item)`. That is
    safe only after provenance has already been established. At the Core/plugin
    boundary an arbitrary object could otherwise stringify to a canonical-looking
    evidence reference. Keep the existing composition/runtime ownership intact,
    but reject non-string references before that normalization can happen.
    """

    if getattr(_base, "_LISP_EVIDENCE_TYPE_FENCE_INSTALLED", False):
        return

    original_handler = _base._handler_outcome_to_invocation_result
    original_core = _base._validated_core_result

    def fenced_handler(expert_id: str, operation: str, outcome: Any):
        _guard_handler_outcome(outcome)
        return original_handler(expert_id, operation, outcome)

    def fenced_core(expert_id: str, operation: str, input_data: Mapping[str, Any], outcome: Any):
        _guard_core_outcome(outcome)
        return original_core(expert_id, operation, input_data, outcome)

    _base._handler_outcome_to_invocation_result = fenced_handler
    _base._validated_core_result = fenced_core
    _base._LISP_EVIDENCE_TYPE_FENCE_INSTALLED = True


__all__ = ["install_lisp_evidence_type_fence"]
