from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .composition import (
    CompositionError,
    InvocationFence,
    SharedSymbolicBudget,
    _normalized_inert_value,
)


_RESULT_KEYS = frozenset(
    {
        "effective",
        "decisions",
        "project_id",
        "project_generation",
        "language",
        "usage",
    }
)
_DECISION_KEYS = frozenset(
    {
        "check",
        "winner",
        "winner_scope",
        "winner_revision",
        "winner_provenance",
        "shadowed",
        "shadowed_provenance",
    }
)
_SHADOW_KEYS = frozenset({"id", "scope", "revision", "provenance"})
_REQUIRED_RULE_KEYS = frozenset(
    {
        "id",
        "scope",
        "language",
        "project_id",
        "project_generation",
        "check",
        "preferred",
        "autofix",
        "provenance",
        "revision",
        "overrides",
    }
)


@dataclass(frozen=True)
class StyleOverlayResolution:
    effective: tuple[Mapping[str, Any], ...]
    decisions: tuple[Mapping[str, Any], ...]
    evidence: tuple[str, ...]
    explanation: str


class PrologRlmStyleOverlayAdapter:
    """Consume the generic Prolog-RLM style resolver without owning its semantics.

    The supplied resolver is the already-owned generic ``style_overlay_resolve/3``
    boundary (or an equivalent transport adapter around it). This product adapter
    only binds Zara's workspace generation and zero-model budget to that contract,
    validates the returned provenance, and rejects late or widened results.

    It creates no registry, scheduler, provider runtime, permission state, style
    precedence engine, or conversation store.
    """

    def __init__(
        self,
        resolver: Callable[[Sequence[Mapping[str, Any]], Mapping[str, Any]], Mapping[str, Any]],
    ) -> None:
        if not callable(resolver):
            raise TypeError("resolver must be callable")
        self._resolver = resolver

    def resolve(
        self,
        rules: Sequence[Mapping[str, Any]],
        *,
        language: str,
        known_languages: Sequence[str],
        budget: SharedSymbolicBudget,
        fence: InvocationFence,
    ) -> StyleOverlayResolution:
        budget.assert_zero_model_usage()
        fence.check()
        normalized_rules = self._validated_rules(rules)
        normalized_languages = self._validated_languages(language, known_languages)
        context = {
            "project_id": fence.workspace_id,
            "project_generation": fence.workspace_generation,
            "language": language,
            "known_languages": list(normalized_languages),
            "max_model_calls": 0,
        }

        try:
            raw = self._resolver(normalized_rules, context)
        except CompositionError:
            raise
        except Exception as exc:
            raise CompositionError(f"upstream style overlay resolver failed: {exc}") from exc

        fence.check()
        budget.assert_zero_model_usage()
        return self._validated_result(
            raw,
            language=language,
            fence=fence,
            submitted_rules=normalized_rules,
        )

    @staticmethod
    def _validated_rules(
        rules: Sequence[Mapping[str, Any]],
    ) -> tuple[Mapping[str, Any], ...]:
        if isinstance(rules, (str, bytes)) or not isinstance(rules, Sequence):
            raise CompositionError("style overlay rules must be a sequence")
        normalized: list[Mapping[str, Any]] = []
        for rule in rules:
            if not isinstance(rule, Mapping):
                raise CompositionError("style overlay rule must be an object")
            if frozenset(rule) != _REQUIRED_RULE_KEYS:
                raise CompositionError("style overlay rule does not match upstream contract")
            inert = _normalized_inert_value(rule)
            if not isinstance(inert, Mapping):
                raise CompositionError("style overlay rule must remain an object")
            normalized.append(dict(inert))
        return tuple(normalized)

    @staticmethod
    def _validated_languages(
        language: str,
        known_languages: Sequence[str],
    ) -> tuple[str, ...]:
        if not isinstance(language, str) or not language:
            raise CompositionError("style overlay language must be non-empty text")
        if isinstance(known_languages, (str, bytes)) or not isinstance(
            known_languages, Sequence
        ):
            raise CompositionError("known style languages must be a sequence")
        normalized: list[str] = []
        seen: set[str] = set()
        for item in known_languages:
            if not isinstance(item, str) or not item:
                raise CompositionError("known style language must be non-empty text")
            if item in seen:
                raise CompositionError("known style languages must be unique")
            seen.add(item)
            normalized.append(item)
        if language not in seen:
            raise CompositionError("style overlay language is not known")
        return tuple(normalized)

    @staticmethod
    def _validated_result(
        raw: Mapping[str, Any],
        *,
        language: str,
        fence: InvocationFence,
        submitted_rules: Sequence[Mapping[str, Any]],
    ) -> StyleOverlayResolution:
        if not isinstance(raw, Mapping):
            raise CompositionError("upstream style overlay result must be an object")
        if frozenset(raw) != _RESULT_KEYS:
            raise CompositionError("upstream style overlay result shape drifted")
        inert = _normalized_inert_value(raw)
        if not isinstance(inert, Mapping):
            raise CompositionError("upstream style overlay result must remain an object")

        if inert.get("project_id") != fence.workspace_id:
            raise CompositionError("upstream style overlay project identity mismatch")
        generation = inert.get("project_generation")
        if type(generation) is not int or generation != fence.workspace_generation:
            raise CompositionError("upstream style overlay project generation mismatch")
        if inert.get("language") != language:
            raise CompositionError("upstream style overlay language mismatch")

        usage = inert.get("usage")
        if not isinstance(usage, Mapping) or frozenset(usage) != {"model_calls"}:
            raise CompositionError("upstream style overlay usage ledger shape drifted")
        model_calls = usage.get("model_calls")
        if type(model_calls) is not int or model_calls != 0:
            raise CompositionError("upstream style overlay attempted model use")

        submitted_by_id: dict[str, Mapping[str, Any]] = {}
        for rule in submitted_rules:
            rule_id = rule.get("id")
            if not isinstance(rule_id, str) or not rule_id or rule_id in submitted_by_id:
                raise CompositionError("submitted style rule identity is invalid")
            submitted_by_id[rule_id] = rule

        effective = PrologRlmStyleOverlayAdapter._objects(
            inert.get("effective"),
            label="effective style rules",
        )
        decisions = PrologRlmStyleOverlayAdapter._objects(
            inert.get("decisions"),
            label="style decisions",
        )
        by_id: dict[str, Mapping[str, Any]] = {}
        for rule in effective:
            if frozenset(rule) != _REQUIRED_RULE_KEYS:
                raise CompositionError("effective style rule shape drifted")
            rule_id = rule.get("id")
            if not isinstance(rule_id, str) or not rule_id or rule_id in by_id:
                raise CompositionError("effective style rule identity is invalid")
            submitted = submitted_by_id.get(rule_id)
            if submitted is None or rule != submitted:
                raise CompositionError("effective style rule was not submitted")
            provenance = rule.get("provenance")
            revision = rule.get("revision")
            check = rule.get("check")
            if not isinstance(provenance, Mapping) or not provenance:
                raise CompositionError("effective style rule is missing provenance")
            if not isinstance(revision, str) or not revision:
                raise CompositionError("effective style rule is missing revision")
            if not isinstance(check, str) or not check:
                raise CompositionError("effective style rule is missing check")
            by_id[rule_id] = rule

        evidence: list[str] = []
        winner_checks: set[str] = set()
        for decision in decisions:
            if frozenset(decision) != _DECISION_KEYS:
                raise CompositionError("style decision shape drifted")
            check = decision.get("check")
            winner = decision.get("winner")
            winner_scope = decision.get("winner_scope")
            winner_revision = decision.get("winner_revision")
            winner_provenance = decision.get("winner_provenance")
            shadowed = decision.get("shadowed")
            shadowed_provenance = decision.get("shadowed_provenance")
            if not isinstance(check, str) or not check or check in winner_checks:
                raise CompositionError("style decision check identity is invalid")
            winner_checks.add(check)
            rule = by_id.get(winner)
            if rule is None or rule.get("check") != check:
                raise CompositionError("style decision winner does not match effective rule")
            if winner_scope != rule.get("scope"):
                raise CompositionError("style decision winner scope mismatch")
            if winner_revision != rule.get("revision"):
                raise CompositionError("style decision winner revision mismatch")
            if winner_provenance != rule.get("provenance"):
                raise CompositionError("style decision winner provenance mismatch")
            if isinstance(shadowed, (str, bytes)) or not isinstance(shadowed, list):
                raise CompositionError("style decision shadowed ids must be a list")
            if isinstance(shadowed_provenance, (str, bytes)) or not isinstance(
                shadowed_provenance, list
            ):
                raise CompositionError("style decision shadowed provenance must be a list")
            if len(shadowed) != len(shadowed_provenance):
                raise CompositionError("style decision shadow provenance is incomplete")
            evidence.append(f"style:{check}:winner:{winner}@{winner_revision}")
            seen_shadow_ids: set[str] = set()
            for shadow_id, shadow in zip(shadowed, shadowed_provenance, strict=True):
                if not isinstance(shadow_id, str) or not shadow_id:
                    raise CompositionError("style shadow identity is invalid")
                if shadow_id == winner or shadow_id in seen_shadow_ids:
                    raise CompositionError("style shadow identity is invalid")
                seen_shadow_ids.add(shadow_id)
                if not isinstance(shadow, Mapping):
                    raise CompositionError("style shadow provenance must be an object")
                if frozenset(shadow) != _SHADOW_KEYS:
                    raise CompositionError("style shadow provenance shape drifted")
                if shadow.get("id") != shadow_id:
                    raise CompositionError("style shadow provenance identity mismatch")
                submitted_shadow = submitted_by_id.get(shadow_id)
                if submitted_shadow is None or submitted_shadow.get("check") != check:
                    raise CompositionError("style shadow was not submitted for decision check")
                expected_shadow = {
                    "id": shadow_id,
                    "scope": submitted_shadow.get("scope"),
                    "revision": submitted_shadow.get("revision"),
                    "provenance": submitted_shadow.get("provenance"),
                }
                if shadow != expected_shadow:
                    raise CompositionError(
                        "style shadow provenance does not match submitted rule"
                    )
                revision = shadow.get("revision")
                provenance = shadow.get("provenance")
                scope = shadow.get("scope")
                if not isinstance(revision, str) or not revision:
                    raise CompositionError("style shadow revision is invalid")
                if not isinstance(provenance, Mapping) or not provenance:
                    raise CompositionError("style shadow provenance is missing")
                if not isinstance(scope, str) or not scope:
                    raise CompositionError("style shadow scope is invalid")
                evidence.append(f"style:{check}:shadowed:{shadow_id}@{revision}")

        if {rule.get("check") for rule in effective} != winner_checks:
            raise CompositionError("style decisions do not cover every effective rule")

        fence.check()
        explanation = (
            f"Prolog-RLM style_overlay_resolve/3 selected {len(effective)} effective "
            f"rule(s) for {language} in {fence.workspace_id}@{fence.workspace_generation}; "
            f"winning and shadowed provenance retained; model_calls=0"
        )
        return StyleOverlayResolution(
            effective=effective,
            decisions=decisions,
            evidence=tuple(evidence),
            explanation=explanation,
        )

    @staticmethod
    def _objects(value: Any, *, label: str) -> tuple[Mapping[str, Any], ...]:
        if isinstance(value, (str, bytes)) or not isinstance(value, list):
            raise CompositionError(f"{label} must be a list")
        objects: list[Mapping[str, Any]] = []
        for item in value:
            if not isinstance(item, Mapping):
                raise CompositionError(f"{label} must contain objects")
            objects.append(dict(item))
        return tuple(objects)


__all__ = ["PrologRlmStyleOverlayAdapter", "StyleOverlayResolution"]
