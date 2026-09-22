from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence

from .composition import (
    CompositionError,
    InvocationFence,
    InvocationResult,
    SharedSymbolicBudget,
)
from .domain import ExpertError, ExpertHost
from .style_runtime import PrologRlmStyleOverlayAdapter, StyleOverlayResolution


STYLE_EXPERT_ID = "zara:expert/style"
STYLE_NAMESPACE = "dotfiles-style-expert"
_SUPPORTED_LANGUAGES = frozenset({"nix", "bash"})
_REGISTERED_PREDICATES: Mapping[str, int] = {
    "style_policy": 3,
    "style_rules_json_hex": 4,
}
_POLICY = "style_policy(disabled,0,0)"
_HEX_RESULT_RE = re.compile(r"^style_rules_json_hex\(.+,'?([0-9a-f]+)'?\)$")
_PAYLOAD_KEYS = frozenset(
    {"project_id", "project_generation", "language", "rules"}
)
_STYLE_COMPOSITION_INPUT_KEYS = frozenset({"language"})
_STYLE_COMPOSITION_OPERATION = "resolve"


@dataclass(frozen=True)
class DotfilesStyleComposition:
    expert_id: str
    rules: tuple[Mapping[str, Any], ...]
    resolution: StyleOverlayResolution
    evidence: tuple[str, ...]
    explanation: str


def _bridge_path() -> Path:
    return Path(__file__).with_name("style_transport_bridge.pl").resolve()


def register_dotfiles_style_expert(
    host: ExpertHost,
    producer_file: str | Path,
    *,
    bridge_file: str | Path | None = None,
) -> None:
    producer = Path(producer_file).expanduser().resolve()
    bridge = Path(bridge_file).expanduser().resolve() if bridge_file else _bridge_path()
    for path in (producer, bridge):
        if not path.is_file():
            raise ExpertError(f"Dotfiles StyleExpert source is not a regular file: {path}")
    files = (str(producer), str(bridge))
    host.preflight_registration(STYLE_NAMESPACE, files, predicates=_REGISTERED_PREDICATES)
    host.register(STYLE_NAMESPACE, files, predicates=_REGISTERED_PREDICATES)


def _single_result(result: Mapping[str, Any], *, predicate: str) -> str:
    if result.get("ok") is not True:
        raise CompositionError(f"Dotfiles StyleExpert predicate {predicate!r} failed")
    raw = result.get("results")
    if isinstance(raw, (str, bytes)) or not isinstance(raw, list) or len(raw) != 1:
        raise CompositionError(
            f"Dotfiles StyleExpert predicate {predicate!r} must return exactly one result"
        )
    value = raw[0]
    if not isinstance(value, str):
        raise CompositionError(
            f"Dotfiles StyleExpert predicate {predicate!r} returned non-text"
        )
    return value


def _query_one(host: ExpertHost, predicate: str, arguments: Sequence[Any], *, fence: InvocationFence) -> str:
    fence.check()
    try:
        result = host.query(STYLE_NAMESPACE, predicate, list(arguments))
    except CompositionError:
        raise
    except Exception as exc:
        raise CompositionError(
            f"Dotfiles StyleExpert registered-predicate dispatch failed: {exc}"
        ) from exc
    fence.check()
    if not isinstance(result, Mapping):
        raise CompositionError("Dotfiles StyleExpert host returned a non-object result")
    return _single_result(result, predicate=predicate)


def _decode_hex_json(encoded: str) -> Mapping[str, Any]:
    if not encoded or len(encoded) % 6 != 0 or not re.fullmatch(r"[0-9a-f]+", encoded):
        raise CompositionError("Dotfiles StyleExpert style rules payload encoding is invalid")
    chars: list[str] = []
    try:
        for offset in range(0, len(encoded), 6):
            codepoint = int(encoded[offset : offset + 6], 16)
            if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
                raise ValueError("invalid Unicode codepoint")
            chars.append(chr(codepoint))
        payload = json.loads("".join(chars))
    except (ValueError, json.JSONDecodeError) as exc:
        raise CompositionError("Dotfiles StyleExpert style rules payload is invalid") from exc
    if not isinstance(payload, Mapping) or frozenset(payload) != _PAYLOAD_KEYS:
        raise CompositionError("Dotfiles StyleExpert style rules payload shape drifted")
    return payload


def _validate_rule_scope_binding(rule: Mapping[str, Any], language: str, *, fence: InvocationFence) -> None:
    scope = rule.get("scope")
    rule_language = rule.get("language")
    project_id = rule.get("project_id")
    generation = rule.get("project_generation")
    if scope in {"library_default", "user_global"}:
        valid = rule_language == "any" and project_id == "any" and generation == "any"
    elif scope == "user_language":
        valid = rule_language == language and project_id == "any" and generation == "any"
    elif scope == "project_global":
        valid = (
            rule_language == "any"
            and project_id == fence.workspace_id
            and type(generation) is int
            and generation == fence.workspace_generation
        )
    elif scope in {"project_language", "session"}:
        valid = (
            rule_language == language
            and project_id == fence.workspace_id
            and type(generation) is int
            and generation == fence.workspace_generation
        )
    else:
        raise CompositionError("Dotfiles StyleExpert rule scope is unsupported")
    if not valid:
        raise CompositionError("Dotfiles StyleExpert rule scope binding mismatch")


def _read_rules(host: ExpertHost, language: str, *, budget: SharedSymbolicBudget, fence: InvocationFence) -> tuple[Mapping[str, Any], ...]:
    budget.assert_zero_model_usage()
    policy = _query_one(host, "style_policy", ({"var": "Policy"}, {"var": "Max"}, {"var": "Used"}), fence=fence)
    if policy != _POLICY:
        raise CompositionError("Dotfiles StyleExpert zero-model policy mismatch")
    raw = _query_one(
        host,
        "style_rules_json_hex",
        (fence.workspace_id, fence.workspace_generation, language, {"var": "Hex"}),
        fence=fence,
    )
    match = _HEX_RESULT_RE.fullmatch(raw)
    if match is None:
        raise CompositionError("Dotfiles StyleExpert style rules payload evidence is malformed")
    payload = _decode_hex_json(match.group(1))
    if payload.get("project_id") != fence.workspace_id:
        raise CompositionError("Dotfiles StyleExpert project identity mismatch")
    generation = payload.get("project_generation")
    if type(generation) is not int or generation != fence.workspace_generation:
        raise CompositionError("Dotfiles StyleExpert project generation mismatch")
    if payload.get("language") != language:
        raise CompositionError("Dotfiles StyleExpert language mismatch")
    rules = payload.get("rules")
    if isinstance(rules, (str, bytes)) or not isinstance(rules, list):
        raise CompositionError("Dotfiles StyleExpert style rules payload must contain a rule list")
    normalized: list[Mapping[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, Mapping):
            raise CompositionError("Dotfiles StyleExpert style rules payload contains non-object rule")
        _validate_rule_scope_binding(rule, language, fence=fence)
        normalized.append(dict(rule))
    fence.check()
    budget.assert_zero_model_usage()
    return tuple(normalized)


def _compose_dotfiles_style(
    host: ExpertHost,
    language: str,
    *,
    resolver: Callable[[Sequence[Mapping[str, Any]], Mapping[str, Any]], Mapping[str, Any]],
    budget: SharedSymbolicBudget,
    fence: InvocationFence,
    charge_evidence: bool,
) -> DotfilesStyleComposition:
    if language not in _SUPPORTED_LANGUAGES:
        raise CompositionError(f"unsupported Dotfiles StyleExpert language: {language!r}")
    budget.assert_zero_model_usage()
    fence.check()
    rules = _read_rules(host, language, budget=budget, fence=fence)
    resolution = PrologRlmStyleOverlayAdapter(resolver).resolve(
        rules,
        language=language,
        known_languages=tuple(sorted(_SUPPORTED_LANGUAGES)),
        budget=budget,
        fence=fence,
    )
    fence.check()
    budget.assert_zero_model_usage()
    evidence = (
        "style-expert:provider_policy=disabled",
        "style-expert:max_model_calls=0",
        "style-expert:model_calls=0",
        f"style-expert:rules={len(rules)}@{fence.workspace_id}:{fence.workspace_generation}",
        *resolution.evidence,
    )
    fence.check()
    if charge_evidence:
        budget.record_evidence(len(evidence))
    budget.assert_zero_model_usage()
    explanation = (
        f"Dotfiles StyleExpert supplied {len(rules)} inert {language} style rule(s) "
        f"through the existing registered-predicate host; {resolution.explanation}"
    )
    return DotfilesStyleComposition(
        expert_id=STYLE_EXPERT_ID,
        rules=rules,
        resolution=resolution,
        evidence=evidence,
        explanation=explanation,
    )


def compose_dotfiles_style(
    host: ExpertHost,
    language: str,
    *,
    resolver: Callable[[Sequence[Mapping[str, Any]], Mapping[str, Any]], Mapping[str, Any]],
    budget: SharedSymbolicBudget,
    fence: InvocationFence,
) -> DotfilesStyleComposition:
    return _compose_dotfiles_style(
        host,
        language,
        resolver=resolver,
        budget=budget,
        fence=fence,
        charge_evidence=True,
    )


class DotfilesStyleCompositionInvoker:
    def __init__(self, host: ExpertHost, *, resolver: Callable[[Sequence[Mapping[str, Any]], Mapping[str, Any]], Mapping[str, Any]]) -> None:
        if not callable(resolver):
            raise TypeError("resolver must be callable")
        self._host = host
        self._resolver = resolver

    def __call__(
        self,
        expert_id: str,
        operation: str,
        input_data: Mapping[str, Any],
        *,
        budget: SharedSymbolicBudget,
        fence: InvocationFence,
        parent_path: tuple[str, ...],
    ) -> InvocationResult:
        del parent_path
        budget.assert_zero_model_usage()
        fence.check()
        if expert_id != STYLE_EXPERT_ID:
            raise CompositionError(f"unsupported StyleExpert identity: {expert_id!r}")
        if operation != _STYLE_COMPOSITION_OPERATION:
            raise CompositionError(f"unsupported StyleExpert operation: {operation!r}")
        if not isinstance(input_data, Mapping) or frozenset(input_data) != _STYLE_COMPOSITION_INPUT_KEYS:
            raise CompositionError("StyleExpert resolve input shape drifted")
        language = input_data.get("language")
        if not isinstance(language, str) or not language:
            raise CompositionError("StyleExpert resolve language must be non-empty text")
        composition = _compose_dotfiles_style(
            self._host,
            language,
            resolver=self._resolver,
            budget=budget,
            fence=fence,
            charge_evidence=False,
        )
        fence.check()
        budget.assert_zero_model_usage()
        return InvocationResult(
            status="succeeded",
            data={
                "language": language,
                "rules": [dict(rule) for rule in composition.rules],
                "effective": [dict(rule) for rule in composition.resolution.effective],
                "decisions": [dict(decision) for decision in composition.resolution.decisions],
            },
            evidence=composition.evidence,
            explanation=composition.explanation,
            model_calls=0,
        )


__all__ = [
    "DotfilesStyleComposition",
    "DotfilesStyleCompositionInvoker",
    "STYLE_EXPERT_ID",
    "STYLE_NAMESPACE",
    "compose_dotfiles_style",
    "register_dotfiles_style_expert",
]
