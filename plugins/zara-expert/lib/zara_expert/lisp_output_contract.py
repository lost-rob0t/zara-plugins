from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from . import lisp_composition as _base
from .composition import CompositionError, InvocationResult
from .lisp_family import (
    _MAX_CORE_EVIDENCE_REFS,
    _REQUIRED_POSTCONDITIONS,
    _VERIFIED_OUTCOME_REF_RE,
    _VERIFIED_POSTCONDITION_PREFIX,
    _verified_postcondition_ref,
)


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
_CONTENT_ADDRESSED_EVIDENCE_PREFIX = "evidence:lisp:sha256:"
_CORE_LISP_EVIDENCE_REF = "ev:core:lisp"


def _invalid(detail: str) -> None:
    raise CompositionError(f"invalid-expert-output: {detail}")


def _is_content_addressed_lisp_evidence(reference: str) -> bool:
    if not reference.startswith(_CONTENT_ADDRESSED_EVIDENCE_PREFIX):
        return False
    digest = reference[len(_CONTENT_ADDRESSED_EVIDENCE_PREFIX) :]
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)


def _validate_projected_evidence(operation: str, evidence: Any) -> None:
    """Admit only canonical Lisp lineage into durable/public projection.

    Core owns invocation/effect authority. The adapter therefore never repairs or
    reinterprets raw trace strings returned by Core. If Core omits canonical
    evidence and only exposes nested trace text, composition fails closed instead
    of projecting strings that could look like provider, tool, or receipt
    authority while the shared model budget is zero.
    """

    if not isinstance(evidence, (list, tuple)):
        _invalid("Lisp projected evidence must be a sequence")
    if len(evidence) > _MAX_CORE_EVIDENCE_REFS:
        _invalid(f"Lisp projected evidence exceeds {_MAX_CORE_EVIDENCE_REFS} references")

    allow_verified_postcondition = operation in {"repair.verify", "repair.apply"}
    for reference in evidence:
        if not isinstance(reference, str) or not reference:
            _invalid("Lisp projected evidence must contain non-empty references")
        if reference == _CORE_LISP_EVIDENCE_REF:
            continue
        if _is_content_addressed_lisp_evidence(reference):
            continue
        if (
            allow_verified_postcondition
            and reference.startswith(_VERIFIED_POSTCONDITION_PREFIX)
            and _VERIFIED_OUTCOME_REF_RE.fullmatch(reference) is not None
        ):
            continue
        _invalid(f"noncanonical Lisp projected evidence reference: {reference!r}")


def _validate_evidence_refs(value: Any, operation: str) -> None:
    try:
        _validate_projected_evidence(operation, value)
    except CompositionError as exc:
        _invalid(f"Lisp data.evidence_refs is invalid: {exc}")


def _validate_repair_verify_postcondition(
    expert_id: str,
    input_data: Mapping[str, Any],
    result: InvocationResult,
) -> None:
    """Bind projected verify success to the exact dialect receipt lineage.

    The trusted host/Core path already owns verification and receipt minting. This
    adapter only checks that a successful public projection refers to the exact
    candidate, source generation, dialect postcondition, and evidence reference
    that the caller asked Core to verify. No verifier or parser semantics live
    here.
    """

    if result.status != "succeeded":
        return

    required_postcondition = _REQUIRED_POSTCONDITIONS.get(expert_id)
    if required_postcondition is None:
        _invalid("generic Lisp repair.verify cannot claim dialect verified success")

    data = result.data
    if data.get("verified") is not True:
        _invalid("Lisp repair.verify success requires literal verified=true")

    source_generation = input_data.get("source_generation")
    if not isinstance(source_generation, str) or not source_generation:
        _invalid("Lisp repair.verify success requires source generation")

    arguments = input_data.get("arguments")
    if not isinstance(arguments, list) or len(arguments) != 2:
        _invalid("Lisp repair.verify success requires original and candidate source")
    candidate_source = arguments[1]
    if not isinstance(candidate_source, str):
        _invalid("Lisp repair.verify success requires string replacement candidate")
    candidate_sha256 = hashlib.sha256(
        candidate_source.encode("utf-8", errors="strict")
    ).hexdigest()

    receipt_ref = data.get("verified_outcome_ref")
    if not isinstance(receipt_ref, str) or not receipt_ref:
        _invalid("Lisp repair.verify success requires verified-outcome receipt reference")
    if not receipt_ref.startswith(_VERIFIED_POSTCONDITION_PREFIX):
        _invalid("Lisp repair.verify success requires postcondition verified-outcome receipt")
    if _VERIFIED_OUTCOME_REF_RE.fullmatch(receipt_ref) is None:
        _invalid("Lisp repair.verify success requires canonical verified-outcome receipt")

    postcondition = data.get("postcondition_evidence")
    if not isinstance(postcondition, Mapping):
        _invalid("Lisp repair.verify success requires postcondition evidence")
    if postcondition.get("receipt_ref") != receipt_ref:
        _invalid("Lisp repair.verify receipt lineage mismatch")
    if postcondition.get("required_postcondition") != required_postcondition:
        _invalid("Lisp repair.verify required postcondition mismatch")
    if postcondition.get("source_generation") != source_generation:
        _invalid("Lisp repair.verify postcondition source generation mismatch")
    if postcondition.get("candidate_sha256") != candidate_sha256:
        _invalid("Lisp repair.verify postcondition candidate digest mismatch")
    if receipt_ref not in result.evidence:
        _invalid("Lisp repair.verify canonical receipt must be projected as evidence reference")


def _validate_repair_apply_postcondition(
    expert_id: str,
    input_data: Mapping[str, Any],
    result: InvocationResult,
) -> None:
    """Bind dialect repair success to the exact canonical postcondition receipt.

    Zara Core owns the edit, approval, verifier execution, and verified-outcome
    receipt. This adapter only refuses to project effect success unless the
    receipt proves that the exact replacement candidate was freshly verified by
    the dialect-specific postcondition requested by the symbolic expert.
    """

    if result.status != "succeeded":
        return

    required_postcondition = _REQUIRED_POSTCONDITIONS.get(expert_id)
    if required_postcondition is None:
        # Generic Lisp has no dialect compiler/reader postcondition contract.
        # Preserve the existing Core postcondition checks rather than inventing
        # a generic parser/verifier authority downstream.
        return

    repair = input_data.get("repair")
    if not isinstance(repair, Mapping):
        _invalid("Lisp repair.apply success requires repair object")
    replacement = repair.get("replacement")
    if not isinstance(replacement, str):
        _invalid("Lisp repair.apply success requires replacement candidate")

    source_generation = input_data.get("source_generation")
    if not isinstance(source_generation, str) or not source_generation:
        _invalid("Lisp repair.apply success requires source generation")

    postcondition = result.data.get("postcondition_evidence")
    if not isinstance(postcondition, Mapping):
        _invalid("Lisp repair.apply success requires postcondition evidence")

    candidate_sha256 = hashlib.sha256(replacement.encode("utf-8", errors="strict")).hexdigest()

    if postcondition.get("expert_id") != expert_id:
        _invalid("Lisp repair.apply postcondition expert identity mismatch")
    if postcondition.get("source_generation") != source_generation:
        _invalid("Lisp repair.apply postcondition source generation mismatch")
    if postcondition.get("required_postcondition") != required_postcondition:
        _invalid("Lisp repair.apply required postcondition mismatch")
    if postcondition.get("candidate_sha256") != candidate_sha256:
        _invalid("Lisp repair.apply postcondition candidate digest mismatch")
    if postcondition.get("verified") is not True:
        _invalid("Lisp repair.apply postcondition must be verified")
    if postcondition.get("fresh") is not True:
        _invalid("Lisp repair.apply postcondition must be fresh")

    receipt_ref = _verified_postcondition_ref(
        postcondition,
        expert_id=expert_id,
        source_generation=source_generation,
        candidate_sha256=candidate_sha256,
        required_postcondition=required_postcondition,
    )
    if receipt_ref is None:
        _invalid("Lisp repair.apply success requires canonical verified-outcome receipt")
    if receipt_ref not in result.evidence:
        _invalid("Lisp repair.apply canonical receipt must be projected as evidence reference")


def _validate_predicate_output(
    expert_id: str,
    operation: str,
    result: InvocationResult,
) -> None:
    data = result.data

    # Cancellation is a terminal generation fence. Core has already discarded
    # late effect receipts before producing InvocationResult; the adapter must
    # also refuse to project any late data or evidence from the cancelled child.
    # Keep this independent of operation shape so repair.apply and dialect
    # delegation cannot become cancellation escape hatches.
    if result.status == "cancelled":
        if not isinstance(data, Mapping) or data or result.evidence:
            raise CompositionError("cancelled-expert-output-leak")
        return

    # repair.apply has a stronger dialect-specific verified-outcome contract.
    # Let that contract reject a malformed receipt first, then apply the generic
    # evidence grammar in the Core wrapper. This preserves a precise fail-closed
    # reason without admitting the bad evidence into projection.
    if operation == "repair.apply":
        return

    _validate_projected_evidence(operation, result.evidence)

    # Dialect repair.preview is a local delegation envelope, not a Core/host
    # predicate result. The canonical generic Lisp child owns the parser output.
    if operation == "repair.preview" and expert_id in _DIALECT_REPAIR_EXPERTS:
        return

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
        _validate_evidence_refs(data["evidence_refs"], operation)

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
        if operation == "repair.verify":
            _validate_repair_verify_postcondition(expert_id, input_data, result)
        return result


class CoreLispFamilyCompositionInvoker(_BaseCoreLispFamilyCompositionInvoker):
    """Core Lisp adapter with fail-closed ZARA-EXPERT/1 output validation."""

    def __call__(self, expert_id: str, operation: str, input_data: Mapping[str, Any], **kwargs):
        result = super().__call__(expert_id, operation, input_data, **kwargs)
        _validate_predicate_output(expert_id, operation, result)
        if operation == "repair.verify":
            _validate_repair_verify_postcondition(expert_id, input_data, result)
        if operation == "repair.apply":
            _validate_repair_apply_postcondition(expert_id, input_data, result)
            _validate_projected_evidence(operation, result.evidence)
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
