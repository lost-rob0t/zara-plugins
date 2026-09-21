from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import lisp_composition as _base
from .composition import CompositionError, InvocationResult


_BaseCoreLispFamilyCompositionInvoker = _base.CoreLispFamilyCompositionInvoker
_BaseLispFamilyCompositionInvoker = _base.LispFamilyCompositionInvoker

_DIALECT_REPAIR_EXPERTS = frozenset(
    {
        "zara:expert/common-lisp",
        "zara:expert/emacs-lisp",
    }
)
_PREDICATE_OUTPUT_FIELDS = frozenset({"result", "evidence_refs"})
_VERIFY_OUTPUT_FIELDS = frozenset(
    {
        "result",
        "evidence_refs",
        "verified",
        "verified_outcome_ref",
        "postcondition_evidence",
    }
)


def _invalid(detail: str) -> None:
    raise CompositionError(f"invalid-expert-output: {detail}")


def _validate_evidence_refs(value: Any) -> None:
    if not isinstance(value, (list, tuple)):
        _invalid("Lisp data.evidence_refs must be a sequence")
    if any(not isinstance(item, str) or not item for item in value):
        _invalid("Lisp data.evidence_refs must contain non-empty references")


def _validate_predicate_output(
    expert_id: str,
    operation: str,
    result: InvocationResult,
) -> None:
    # Dialect repair.preview is a local delegation envelope, not a Core/host
    # predicate result. The canonical generic Lisp child owns the parser output.
    if operation == "repair.preview" and expert_id in _DIALECT_REPAIR_EXPERTS:
        return
    if operation == "repair.apply":
        # The existing Core adapter already enforces the canonical effect receipt
        # and fresh postcondition contract. Do not invent a second effect schema.
        return

    data = result.data
    if not isinstance(data, Mapping):
        _invalid("Lisp result data must be an object")

    allowed = _VERIFY_OUTPUT_FIELDS if operation == "repair.verify" else _PREDICATE_OUTPUT_FIELDS
    unknown = set(data) - allowed
    if unknown:
        _invalid(f"unsupported Lisp output fields: {sorted(unknown)!r}")

    nested = data.get("result")
    if not isinstance(nested, Mapping):
        _invalid("Lisp predicate output requires result object")

    if "evidence_refs" in data:
        _validate_evidence_refs(data["evidence_refs"])

    if operation != "repair.verify":
        return

    if "verified" in data and data["verified"] is not True:
        _invalid("Lisp repair.verify verified must be literal true when present")
    if "verified_outcome_ref" in data:
        reference = data["verified_outcome_ref"]
        if not isinstance(reference, str) or not reference:
            _invalid("Lisp repair.verify verified_outcome_ref must be a non-empty reference")
    if "postcondition_evidence" in data and not isinstance(
        data["postcondition_evidence"], Mapping
    ):
        _invalid("Lisp repair.verify postcondition_evidence must be an object")


class LispFamilyCompositionInvoker(_BaseLispFamilyCompositionInvoker):
    """Public Lisp adapter with fail-closed ZARA-EXPERT/1 output validation."""

    def __call__(self, expert_id: str, operation: str, input_data: Mapping[str, Any], **kwargs):
        result = super().__call__(expert_id, operation, input_data, **kwargs)
        _validate_predicate_output(expert_id, operation, result)
        return result


class CoreLispFamilyCompositionInvoker(_BaseCoreLispFamilyCompositionInvoker):
    """Core Lisp adapter with fail-closed ZARA-EXPERT/1 output validation."""

    def __call__(self, expert_id: str, operation: str, input_data: Mapping[str, Any], **kwargs):
        result = super().__call__(expert_id, operation, input_data, **kwargs)
        _validate_predicate_output(expert_id, operation, result)
        return result


# Any import of zara_expert.lisp_composition first initializes the package. Keep
# the historical module path canonical while layering this contract on the
# existing implementation rather than forking parser/delegation/effect semantics.
_base.LispFamilyCompositionInvoker = LispFamilyCompositionInvoker
_base.CoreLispFamilyCompositionInvoker = CoreLispFamilyCompositionInvoker


__all__ = [
    "CoreLispFamilyCompositionInvoker",
    "LispFamilyCompositionInvoker",
]
