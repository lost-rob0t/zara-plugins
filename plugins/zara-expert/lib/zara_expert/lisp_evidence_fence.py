from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import lisp_composition as _base
from . import lisp_family as _family
from .composition import CompositionError
from .domain import ExpertError


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


def _strict_family_core_evidence_refs(result: Mapping[str, Any]) -> list[str]:
    """Preserve trace-first evidence projection without widening result objects."""

    raw_trace = result.get("trace", ())
    if isinstance(raw_trace, (str, bytes)) or not isinstance(raw_trace, (list, tuple)):
        raise ExpertError("Lisp expert trace must be a sequence")
    if len(raw_trace) > _family._MAX_CORE_EVIDENCE_REFS:
        raise ExpertError(
            f"Lisp expert trace exceeds {_family._MAX_CORE_EVIDENCE_REFS} entries"
        )
    if raw_trace:
        if any(not isinstance(item, str) for item in raw_trace):
            raise ExpertError("Lisp expert trace entries must be strings")
        return [_family._content_addressed_evidence_ref(item) for item in raw_trace]

    raw_results = result.get("results", ())
    if isinstance(raw_results, (str, bytes)) or not isinstance(raw_results, (list, tuple)):
        raise ExpertError("Lisp expert results must be a sequence")
    if len(raw_results) > _family._MAX_CORE_EVIDENCE_REFS:
        raise ExpertError(
            f"Lisp expert evidence exceeds {_family._MAX_CORE_EVIDENCE_REFS} entries"
        )
    if any(not isinstance(item, str) for item in raw_results):
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
    if any(not isinstance(item, str) for item in raw_results):
        raise ExpertError("Lisp expert result entries must be strings")
    if not any("verified(false)" in item for item in raw_results):
        return None
    required: set[str] = set()
    for item in raw_results:
        required.update(_family._REQUIRED_POSTCONDITION_RE.findall(item))
    if required != {expected}:
        return None
    return expected


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
    result terms and receipt-binding inputs: only canonical built-in strings/lists
    may influence verified success. Keep existing composition/runtime ownership
    intact and do not duplicate parser semantics.
    """

    if getattr(_base, "_LISP_EVIDENCE_TYPE_FENCE_INSTALLED", False):
        return

    original_handler = _base._handler_outcome_to_invocation_result
    original_core = _base._validated_core_result
    original_make_handler = _family.make_lisp_expert_handler

    def fenced_handler(expert_id: str, operation: str, outcome: Any):
        _guard_handler_outcome(outcome)
        return original_handler(expert_id, operation, outcome)

    def fenced_core(expert_id: str, operation: str, input_data: Mapping[str, Any], outcome: Any):
        _guard_core_outcome(outcome)
        return original_core(expert_id, operation, input_data, outcome)

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
    _family.make_lisp_expert_handler = fenced_make_handler
    _base._LISP_EVIDENCE_TYPE_FENCE_INSTALLED = True


__all__ = ["install_lisp_evidence_type_fence"]
