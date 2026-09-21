from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from typing import Any

from .domain import ExpertError, ExpertHost
from .language_family import (
    MAX_MODEL_CALLS,
    invoke_language_operation,
    language_expert_schemas,
    language_family_specs,
)


_EXPERT_IDS = frozenset(spec.expert_id for spec in language_family_specs())
_EXPERT_KEYS = frozenset(spec.key for spec in language_family_specs())
_RESULT_VARIABLE = {"var": "Result"}
_MAX_CORE_EVIDENCE_REFS = 32
_VERIFIED_OUTCOME_REF_RE = re.compile(
    r"^zara\.verified-outcome/v1:(?:effect|outcome):"
    r"[A-Za-z0-9][A-Za-z0-9._:/#-]{0,383}$"
)
_VERIFIED_POSTCONDITION_PREFIX = "zara.verified-outcome/v1:outcome:postcondition/"
_REQUIRED_POSTCONDITION_RE = re.compile(
    r"required_postcondition\(([a-z][a-z0-9_]*)\)"
)
_FRESH_POSTCONDITION_RE = re.compile(
    r"fresh_postcondition_required\(([a-z][a-z0-9_]*)\)"
)
_REQUIRED_POSTCONDITIONS = {
    "zara:expert/nix": "parse_then_eval_or_check",
    "zara:expert/bash": "parse_and_bash_n",
}
_CLOSED_OPERATION_PROJECTION_EXPERTS = frozenset(
    {
        "zara:expert/prolog",
        "zara:expert/python",
        "zara:expert/nim",
        "zara:expert/javascript",
        "zara:expert/typescript",
        "zara:expert/java",
        "zara:expert/kotlin",
    }
)
VerifiedOutcomeResolver = Callable[..., Mapping[str, Any] | None]


def _canonical_expert_id(expert_id: str) -> str:
    if expert_id in _EXPERT_IDS:
        return expert_id
    if expert_id in _EXPERT_KEYS:
        return f"zara:expert/{expert_id}"
    raise ExpertError(f"unknown language expert: {expert_id!r}")


def _operation_arguments(expert_operation: str, payload: dict[str, Any]) -> list[Any]:
    schemas = language_expert_schemas()
    schema = schemas.get(expert_operation)
    if schema is None:
        raise ExpertError(f"unsupported language expert operation: {expert_operation!r}")

    fields = schema["input_schema"]["fields"]
    allowed = {field["name"] for field in fields}
    unknown = set(payload) - allowed
    if unknown:
        raise ExpertError(
            f"unknown input field for {expert_operation!r}: {sorted(unknown)[0]!r}"
        )
    missing = [
        field["name"]
        for field in fields
        if field["required"] and field["name"] not in payload
    ]
    if missing:
        raise ExpertError(
            f"missing required input field for {expert_operation!r}: {missing[0]!r}"
        )

    # Registered language predicates reserve their final argument for this
    # adapter-created result variable. User payloads are inert ground values and
    # can never manufacture Prolog variable authority.
    return [payload.get(field["name"]) for field in fields] + [dict(_RESULT_VARIABLE)]


def _evidence_refs(result: dict[str, Any]) -> list[str]:
    raw = result.get("evidence", ())
    if isinstance(raw, (str, bytes)) or not isinstance(raw, (list, tuple)):
        raise ExpertError("language expert evidence must be a sequence")
    if len(raw) > _MAX_CORE_EVIDENCE_REFS:
        raise ExpertError(
            f"language expert evidence exceeds {_MAX_CORE_EVIDENCE_REFS} entries"
        )

    refs: list[str] = []
    for item in raw:
        encoded = str(item).encode("utf-8", errors="strict")
        digest = hashlib.sha256(encoded).hexdigest()
        refs.append(f"evidence:language:sha256:{digest}")
    return refs


def _symbolic_terms(result: Mapping[str, Any]) -> list[str]:
    raw = result.get("evidence", ())
    if isinstance(raw, (str, bytes)) or not isinstance(raw, (list, tuple)):
        raise ExpertError("language expert evidence must be a sequence")
    terms = [str(item) for item in raw]
    if not terms:
        raise ExpertError("language expert succeeded without symbolic output")
    return terms


def _literal_marker(terms: list[str], name: str) -> bool:
    true_marker = f"{name}(true)"
    false_marker = f"{name}(false)"
    has_true = any(true_marker in term for term in terms)
    has_false = any(false_marker in term for term in terms)
    if has_true == has_false:
        raise ExpertError(f"language expert output has ambiguous {name!r} marker")
    return has_true


def _closed_operation_data(
    operation: str,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    """Project trusted registered-predicate output into declared package data.

    The Dotfiles language brains return bounded Prolog terms as inert strings.
    Keep those terms as provenance-bearing symbolic evidence while mapping them
    into the closed ZARA-EXPERT/1 operation schemas consumed by language expert
    packages. No source term is executed or reinterpreted as capability
    authority here.
    """

    terms = _symbolic_terms(result)
    if operation == "match":
        return {"applicable": _literal_marker(terms, "applicable")}
    if operation == "inspect":
        return {"result": dict(result)}
    if operation == "diagnose":
        return {"diagnostics": terms}
    if operation == "repair.preview":
        return {"repair": {"symbolic_terms": terms}}
    if operation == "repair.verify":
        return {
            "verified": _literal_marker(terms, "verified"),
            "postcondition_evidence": {
                "symbolic_terms": terms,
                "fresh": False,
            },
        }
    if operation == "style.rules":
        source_reference = result.get("source_reference")
        if not isinstance(source_reference, str) or not source_reference:
            raise ExpertError("language style output is missing source provenance")
        return {
            "style_rules": terms,
            "style_provenance": [source_reference],
        }
    if operation == "explain":
        raw_trace = result.get("explanation", ())
        if isinstance(raw_trace, (str, bytes)) or not isinstance(raw_trace, (list, tuple)):
            raise ExpertError("language expert explanation must be a sequence")
        return {
            "explanation": {
                "symbolic_terms": terms,
                "trace": [str(item) for item in raw_trace],
            }
        }
    raise ExpertError(f"unsupported closed language output operation: {operation!r}")


def _pending_postcondition(
    canonical_id: str,
    result: Mapping[str, Any],
) -> str | None:
    """Return the one canonical pending Nix/Bash postcondition, if explicit."""

    expected = _REQUIRED_POSTCONDITIONS.get(canonical_id)
    if expected is None:
        return None

    raw = result.get("evidence", ())
    if isinstance(raw, (str, bytes)) or not isinstance(raw, (list, tuple)):
        return None
    rendered = tuple(str(item) for item in raw)
    if not any("verified(false)" in item for item in rendered):
        return None

    required: set[str] = set()
    fresh: set[str] = set()
    for item in rendered:
        required.update(_REQUIRED_POSTCONDITION_RE.findall(item))
        fresh.update(_FRESH_POSTCONDITION_RE.findall(item))
    if required != {expected} or fresh != {expected}:
        return None
    return expected


def _verified_postcondition_ref(
    receipt: Any,
    *,
    expert_id: str,
    source_generation: str,
    candidate_sha256: str,
    required_postcondition: str,
) -> str | None:
    """Validate a trusted Core verified-outcome receipt without executing tools."""

    if not isinstance(receipt, Mapping):
        return None
    receipt_ref = receipt.get("receipt_ref")
    if not isinstance(receipt_ref, str):
        return None
    if not receipt_ref.startswith(_VERIFIED_POSTCONDITION_PREFIX):
        return None
    if _VERIFIED_OUTCOME_REF_RE.fullmatch(receipt_ref) is None:
        return None
    if receipt.get("expert_id") != expert_id:
        return None
    if receipt.get("source_generation") != source_generation:
        return None
    if receipt.get("candidate_sha256") != candidate_sha256:
        return None
    if receipt.get("required_postcondition") != required_postcondition:
        return None
    if type(receipt.get("verified")) is not bool or receipt["verified"] is not True:
        return None
    if type(receipt.get("fresh")) is not bool or receipt["fresh"] is not True:
        return None
    return receipt_ref


def make_language_expert_handler(
    host: ExpertHost,
    expert_id: str,
    *,
    verified_outcome_resolver: VerifiedOutcomeResolver | None = None,
):
    """Return a Core-owned ZARA-EXPERT/1 handler for one language expert.

    ``expert_operation`` is trusted host metadata injected by Zara Core. The
    remaining keyword payload is validated against the selected descriptor
    schema, converted to the registered-predicate ABI, and dispatched through
    the existing ExpertHost capability boundary. Pure-symbolic outcomes always
    expose an exact zero model-call ledger. Filesystem repair remains outside
    this adapter and must cross Zara's typed effect/approval path before fresh
    postcondition verification.

    ``verified_outcome_resolver`` is an optional trusted host seam for reading an
    already-produced Zara verified-outcome receipt. It is never operation input
    and does not execute Nix, Bash, tools, effects, providers, or network calls.
    A Nix/Bash ``repair.verify`` result can become successful only when the
    symbolic brain explicitly requests its canonical fresh postcondition and the
    resolver returns a receipt bound to that exact expert, source generation,
    candidate digest, and postcondition. Missing, stale, malformed, mismatched,
    or resolver-error evidence fails closed as ``blocked``.
    """

    canonical_id = _canonical_expert_id(expert_id)
    if verified_outcome_resolver is not None and not callable(verified_outcome_resolver):
        raise TypeError("verified_outcome_resolver must be callable")

    def handler(*, expert_operation: str, **payload: Any) -> dict[str, Any]:
        if expert_operation == "repair.apply":
            # Core validates the public repair.apply schema before dispatch. The
            # plugin still refuses to write: actual mutation must cross Zara's
            # typed capability/approval/effect path and then fresh verification.
            return {
                "verdict": "blocked",
                "data": {
                    "reason": "canonical-typed-edit-required",
                    "expert_id": canonical_id,
                },
                "evidence_refs": [],
                "usage": {"model_calls": MAX_MODEL_CALLS},
                "effect_receipts": [],
            }

        arguments = _operation_arguments(expert_operation, payload)
        result = invoke_language_operation(
            host,
            canonical_id,
            expert_operation,
            arguments,
        )
        evidence_refs = _evidence_refs(result)
        verdict = result["verdict"]
        if canonical_id in _CLOSED_OPERATION_PROJECTION_EXPERTS:
            data = (
                _closed_operation_data(expert_operation, result)
                if verdict == "succeeded"
                else {}
            )
        else:
            data = {"result": result}
        if expert_operation == "repair.verify" and verdict == "succeeded":
            # Predicate completion only proves the symbolic verifier ran. A
            # successful query does not mean the candidate passed its required
            # postcondition. Preserve the existing fail-closed verdict for every
            # language family; only the canonical verified-outcome path below
            # may promote a supported operation back to succeeded.
            verdict = "blocked"
            if canonical_id in _CLOSED_OPERATION_PROJECTION_EXPERTS:
                # Closed language packages intentionally require non-success
                # projections to carry no data. Keep hashed evidence references
                # for diagnosis, but never let a blocked symbolic verifier leak
                # provider-shaped or stale result payload through the adapter.
                data = {}
            required_postcondition = _pending_postcondition(canonical_id, result)
            candidate_source = payload.get("candidate_source")
            source_generation = payload.get("source_generation")
            if (
                required_postcondition is not None
                and verified_outcome_resolver is not None
                and isinstance(candidate_source, str)
                and isinstance(source_generation, str)
                and len(evidence_refs) < _MAX_CORE_EVIDENCE_REFS
            ):
                candidate_sha256 = hashlib.sha256(
                    candidate_source.encode("utf-8", errors="strict")
                ).hexdigest()
                try:
                    receipt = verified_outcome_resolver(
                        expert_id=canonical_id,
                        source_generation=source_generation,
                        candidate_sha256=candidate_sha256,
                        required_postcondition=required_postcondition,
                    )
                except Exception:
                    receipt = None
                receipt_ref = _verified_postcondition_ref(
                    receipt,
                    expert_id=canonical_id,
                    source_generation=source_generation,
                    candidate_sha256=candidate_sha256,
                    required_postcondition=required_postcondition,
                )
                if receipt_ref is not None:
                    verdict = "succeeded"
                    evidence_refs.append(receipt_ref)
                    data.update(
                        {
                            "verified": True,
                            "verified_outcome_ref": receipt_ref,
                            "postcondition_evidence": {
                                "receipt_ref": receipt_ref,
                                "required_postcondition": required_postcondition,
                                "source_generation": source_generation,
                                "candidate_sha256": candidate_sha256,
                            },
                        }
                    )
        return {
            "verdict": verdict,
            "data": data,
            "evidence_refs": evidence_refs,
            "usage": {"model_calls": MAX_MODEL_CALLS},
            "effect_receipts": [],
        }

    return handler


__all__ = ["VerifiedOutcomeResolver", "make_language_expert_handler"]
