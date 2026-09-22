from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import lisp_composition as _base
from . import lisp_family as _family
from .composition import CompositionError
from .domain import ExpertError


_RECEIPT_STRING_FIELDS = (
    "receipt_ref",
    "expert_id",
    "source_generation",
    "candidate_sha256",
    "required_postcondition",
)
_RECEIPT_BOOL_FIELDS = ("verified", "fresh")
_POSTCONDITION_STRING_FIELDS = _RECEIPT_STRING_FIELDS + ("observed_generation",)


def _require_string_references(value: Any, label: str) -> None:
    """Reject object-to-string authority widening before base normalization.

    The canonical Lisp output contract decides which *strings* are admissible
    evidence references. This guard only preserves that type boundary; it does
    not define evidence grammar, parser semantics, or receipt authority.
    """

    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        return
    if type(value) not in (list, tuple):
        raise CompositionError(f"{label} must be a built-in list or tuple")
    if any(type(item) is not str for item in value):
        raise CompositionError(f"{label} must contain strings")


def _require_plain_postcondition_evidence(data: Any) -> None:
    """Keep verified-outcome evidence on canonical host-language wire types.

    Output validation reads postcondition bindings more than once before the
    result is persisted/rendered. Mapping and string subclasses can change those
    bindings or equality semantics between checks. Reject non-built-in receipt
    containers and authority-bearing scalar strings before the existing receipt
    grammar is evaluated; Core remains the sole verifier/receipt authority.
    """

    if not isinstance(data, Mapping):
        return
    postcondition = data.get("postcondition_evidence")
    if postcondition is None:
        return
    if type(postcondition) is not dict:
        raise CompositionError("Lisp postcondition evidence must be a built-in dict")
    for field in _POSTCONDITION_STRING_FIELDS:
        if field not in postcondition:
            continue
        if type(postcondition[field]) is not str:
            raise CompositionError(
                f"Lisp postcondition evidence {field} must be a built-in string"
            )


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
    _require_plain_postcondition_evidence(data)
    nested = data.get("result")
    if not isinstance(nested, Mapping):
        return
    _require_string_references(nested.get("trace", ()), "Lisp expert host trace")


def _guard_core_outcome(outcome: Any) -> None:
    evidence_refs = getattr(outcome, "evidence_refs", None)
    _require_string_references(evidence_refs, "Core Lisp expert evidence_refs")

    data = getattr(outcome, "data", None)
    if isinstance(data, Mapping):
        _require_plain_postcondition_evidence(data)

    if evidence_refs:
        return

    if not isinstance(data, Mapping):
        return
    nested = data.get("result")
    if not isinstance(nested, Mapping):
        return
    _require_string_references(nested.get("trace", ()), "Core Lisp expert host trace")


def _strict_family_core_evidence_refs(result: Mapping[str, Any]) -> list[str]:
    """Preserve trace-first evidence projection without widening result objects."""

    raw_trace = result.get("trace", ())
    if isinstance(raw_trace, (str, bytes)) or not isinstance(raw_trace, (list, tuple)):
        raise ExpertError("Lisp expert trace must be a sequence")
    if type(raw_trace) not in (list, tuple):
        raise ExpertError("Lisp expert trace must be a built-in list or tuple")
    if len(raw_trace) > _family._MAX_CORE_EVIDENCE_REFS:
        raise ExpertError(
            f"Lisp expert trace exceeds {_family._MAX_CORE_EVIDENCE_REFS} entries"
        )
    if raw_trace:
        if any(type(item) is not str for item in raw_trace):
            raise ExpertError("Lisp expert trace entries must be strings")
        return [_family._content_addressed_evidence_ref(item) for item in raw_trace]

    raw_results = result.get("results", ())
    if isinstance(raw_results, (str, bytes)) or not isinstance(raw_results, (list, tuple)):
        raise ExpertError("Lisp expert results must be a sequence")
    if type(raw_results) not in (list, tuple):
        raise ExpertError("Lisp expert results must be a built-in list or tuple")
    if len(raw_results) > _family._MAX_CORE_EVIDENCE_REFS:
        raise ExpertError(
            f"Lisp expert evidence exceeds {_family._MAX_CORE_EVIDENCE_REFS} entries"
        )
    if any(type(item) is not str for item in raw_results):
        raise ExpertError("Lisp expert result entries must be strings")
    return [_family._content_addressed_evidence_ref(item) for item in raw_results]


def _strict_family_pending_postcondition(
    spec: _family.LispExpertSpec,
    result: Mapping[str, Any],
) -> str | None:
    """Interpret verified-outcome terms only from already-typed symbolic strings."""

    expected = _family._REQUIRED_POSTCONDITIONS.get(spec.expert_id)
    if expected is None:
        return None
    raw_results = result.get("results", ())
    if isinstance(raw_results, (str, bytes)) or not isinstance(raw_results, (list, tuple)):
        raise ExpertError("Lisp expert results must be a sequence")
    if type(raw_results) not in (list, tuple):
        raise ExpertError("Lisp expert results must be a built-in list or tuple")
    if any(type(item) is not str for item in raw_results):
        raise ExpertError("Lisp expert result entries must be strings")
    if not any("verified(false)" in item for item in raw_results):
        return None
    required: set[str] = set()
    for item in raw_results:
        required.update(_family._REQUIRED_POSTCONDITION_RE.findall(item))
    if required != {expected}:
        return None
    return expected


def _snapshot_verified_postcondition_receipt(receipt: Any) -> dict[str, Any] | None:
    """Snapshot canonical receipt wire values once before identity comparison.

    A trusted resolver may still surface deserialized/custom mapping objects. Do
    not let Python string subclasses override equality at the fresh receipt
    binding boundary, and do not re-read stateful mapping values during
    validation. This preserves the existing receipt grammar/authority while
    narrowing only the host-language type seam.
    """

    if not isinstance(receipt, Mapping):
        return None

    snapshot: dict[str, Any] = {}
    try:
        for field in _RECEIPT_STRING_FIELDS:
            value = receipt.get(field)
            if type(value) is not str:
                return None
            snapshot[field] = value
        for field in _RECEIPT_BOOL_FIELDS:
            value = receipt.get(field)
            if type(value) is not bool:
                return None
            snapshot[field] = value
    except Exception:
        return None
    return snapshot


def _guard_repair_verify_input_identity(
    expert_operation: Any,
    arguments: Any,
    source_generation: Any,
) -> None:
    """Keep receipt-binding inputs canonical before registered-host dispatch.

    `repair.verify` binds fresh postcondition evidence to the exact candidate
    source bytes and source generation. Python container/string subclasses are
    not canonical ZARA-EXPERT/1 wire values and can override iteration, encoding,
    or comparison behavior. Reject them before they can influence the host query
    or candidate digest. This is a type/authority fence, not Lisp parser logic.
    """

    if expert_operation != "repair.verify":
        return
    if arguments is not None and type(arguments) is not list:
        raise ExpertError("Lisp expert arguments must be a list of ground strings")
    if arguments is not None and any(type(item) is not str for item in arguments):
        raise ExpertError("Lisp expert arguments must contain ground strings")
    if source_generation is not None and type(source_generation) is not str:
        raise ExpertError("Lisp expert source_generation must be a string")


def install_lisp_evidence_type_fence() -> None:
    """Install narrow pre-normalization fences on the existing Lisp adapters.

    `lisp_composition` historically normalizes evidence with `str(item)`. That is
    safe only after provenance has already been established. At the Core/plugin
    boundary an arbitrary object could otherwise stringify to a canonical-looking
    evidence reference. The verified-outcome path has the same rule for symbolic
    result terms, receipt-binding inputs, receipt identity fields, and receipt
    evidence containers: only canonical built-in strings/lists/dicts/bools may
    influence verified success. Keep existing composition/runtime ownership intact
    and do not duplicate parser semantics.
    """

    if getattr(_base, "_LISP_EVIDENCE_TYPE_FENCE_INSTALLED", False):
        return

    original_handler = _base._handler_outcome_to_invocation_result
    original_core = _base._validated_core_result
    original_make_handler = _family.make_lisp_expert_handler
    original_verified_postcondition_ref = _family._verified_postcondition_ref

    def fenced_handler(expert_id: str, operation: str, outcome: Any):
        _guard_handler_outcome(outcome)
        return original_handler(expert_id, operation, outcome)

    def fenced_core(expert_id: str, operation: str, input_data: Mapping[str, Any], outcome: Any):
        _guard_core_outcome(outcome)
        return original_core(expert_id, operation, input_data, outcome)

    def fenced_verified_postcondition_ref(
        receipt: Any,
        *,
        expert_id: str,
        source_generation: str,
        candidate_sha256: str,
        required_postcondition: str,
    ) -> str | None:
        snapshot = _snapshot_verified_postcondition_receipt(receipt)
        if snapshot is None:
            return None
        return original_verified_postcondition_ref(
            snapshot,
            expert_id=expert_id,
            source_generation=source_generation,
            candidate_sha256=candidate_sha256,
            required_postcondition=required_postcondition,
        )

    def fenced_make_handler(
        host: Any,
        expert_id: str,
        *,
        verified_outcome_resolver: _family.VerifiedOutcomeResolver | None = None,
    ):
        handler = original_make_handler(
            host,
            expert_id,
            verified_outcome_resolver=verified_outcome_resolver,
        )

        def fenced_invocation(
            *,
            expert_operation: str,
            arguments: list[Any] | None = None,
            repair: dict[str, Any] | None = None,
            expected_preimage: str | None = None,
            source_generation: str | None = None,
        ) -> dict[str, Any]:
            _guard_repair_verify_input_identity(
                expert_operation,
                arguments,
                source_generation,
            )
            return handler(
                expert_operation=expert_operation,
                arguments=arguments,
                repair=repair,
                expected_preimage=expected_preimage,
                source_generation=source_generation,
            )

        return fenced_invocation

    _base._handler_outcome_to_invocation_result = fenced_handler
    _base._validated_core_result = fenced_core
    _family._core_evidence_refs = _strict_family_core_evidence_refs
    _family._pending_postcondition = _strict_family_pending_postcondition
    _family._verified_postcondition_ref = fenced_verified_postcondition_ref
    _family.make_lisp_expert_handler = fenced_make_handler
    _base._LISP_EVIDENCE_TYPE_FENCE_INSTALLED = True


__all__ = ["install_lisp_evidence_type_fence"]
