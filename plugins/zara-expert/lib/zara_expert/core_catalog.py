from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .composition import CompositionError, InvocationFence, _normalized_inert_value


_SELECTABLE_AVAILABILITY = frozenset({"installed", "available", "ready"})
_MATCH_FIELDS = frozenset({"expert_id", "score", "matched_keywords"})


class CoreExpertRegistry(Protocol):
    """Subset of Zara Core's one canonical ZARA-EXPERT/1 registry used here."""

    def snapshot(self) -> Any: ...

    def list_experts(
        self,
        principal: str,
        *,
        offset: int = 0,
        limit: int = 32,
    ) -> Mapping[str, Any]: ...

    def describe(self, expert_id: str) -> Mapping[str, Any]: ...

    def match(self, goal_text: str) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True)
class CoreExpertSelection:
    expert_id: str
    score: int
    matched_keywords: tuple[str, ...]
    registry_generation: int
    runtime_generation: int
    descriptor: Mapping[str, Any]
    explanation: str


@dataclass(frozen=True)
class _GenerationPair:
    registry: int
    runtime: int


def _builtin_nonnegative_int(value: Any, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise CompositionError(f"{field_name} must be a non-negative built-in integer")
    return value


def _inert_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CompositionError(f"{field_name} must be an object")
    normalized = _normalized_inert_value(value)
    if not isinstance(normalized, dict):
        raise CompositionError(f"{field_name} must normalize to an object")
    return normalized


class CoreExpertCatalogAdapter:
    """Fail-closed discovery facade over Zara Core's existing ExpertRegistry.

    This class owns no registry state. Every discovery/selection operation is read
    directly from the caller-supplied canonical registry and is rejected if either
    its registry or runtime generation changes before the result can be returned.
    """

    PAGE_LIMIT = 128

    def __init__(self, registry: CoreExpertRegistry, *, principal: str) -> None:
        if not isinstance(principal, str) or not principal or principal != principal.strip():
            raise ValueError("principal must be non-empty trimmed text")
        self._registry = registry
        self._principal = principal

    def _generation_pair(self) -> _GenerationPair:
        snapshot = self._registry.snapshot()
        registry_generation = _builtin_nonnegative_int(
            getattr(snapshot, "generation", None),
            field_name="registry generation",
        )
        runtime_generation = _builtin_nonnegative_int(
            getattr(snapshot, "runtime_generation", None),
            field_name="runtime generation",
        )
        return _GenerationPair(registry_generation, runtime_generation)

    def _assert_current(
        self,
        expected: _GenerationPair,
        *,
        fence: InvocationFence | None,
    ) -> None:
        if fence is not None:
            fence.check()
        current = self._generation_pair()
        if current.registry != expected.registry:
            raise CompositionError("stale expert registry generation")
        if current.runtime != expected.runtime:
            raise CompositionError("stale expert runtime generation")

    @staticmethod
    def _validate_expert_id(value: Any, *, field_name: str = "expert_id") -> str:
        if not isinstance(value, str) or not value or value != value.strip():
            raise CompositionError(f"{field_name} must be non-empty trimmed text")
        return value

    def list(self, *, fence: InvocationFence | None = None) -> tuple[Mapping[str, Any], ...]:
        if fence is not None:
            fence.check()
        expected = self._generation_pair()
        offset = 0
        total: int | None = None
        experts: list[Mapping[str, Any]] = []
        seen: set[str] = set()

        while total is None or offset < total:
            if fence is not None:
                fence.check()
            raw_page = self._registry.list_experts(
                self._principal,
                offset=offset,
                limit=self.PAGE_LIMIT,
            )
            page = _inert_mapping(raw_page, field_name="expert catalog page")
            page_generation = _builtin_nonnegative_int(
                page.get("registry_generation"),
                field_name="catalog registry generation",
            )
            if page_generation != expected.registry:
                raise CompositionError("stale expert catalog page generation")
            page_offset = _builtin_nonnegative_int(
                page.get("offset"),
                field_name="catalog offset",
            )
            if page_offset != offset:
                raise CompositionError("expert catalog page offset changed")
            page_limit = _builtin_nonnegative_int(
                page.get("limit"),
                field_name="catalog limit",
            )
            if page_limit != self.PAGE_LIMIT:
                raise CompositionError("expert catalog page limit changed")
            page_total = _builtin_nonnegative_int(
                page.get("total"),
                field_name="catalog total",
            )
            if total is None:
                total = page_total
            elif total != page_total:
                raise CompositionError("expert catalog total changed during discovery")

            raw_experts = page.get("experts")
            if not isinstance(raw_experts, list):
                raise CompositionError("expert catalog experts must be a list")
            if not raw_experts and offset < total:
                raise CompositionError("expert catalog stopped before declared total")
            for raw_expert in raw_experts:
                expert = _inert_mapping(raw_expert, field_name="expert catalog entry")
                expert_id = self._validate_expert_id(expert.get("expert_id"))
                if expert_id in seen:
                    raise CompositionError(f"duplicate expert catalog entry: {expert_id}")
                seen.add(expert_id)
                experts.append(expert)
            offset += len(raw_experts)
            if offset > total:
                raise CompositionError("expert catalog returned more entries than declared")

        self._assert_current(expected, fence=fence)
        return tuple(experts)

    def describe(
        self,
        expert_id: str,
        *,
        fence: InvocationFence | None = None,
    ) -> Mapping[str, Any]:
        expert_id = self._validate_expert_id(expert_id)
        if fence is not None:
            fence.check()
        expected = self._generation_pair()
        descriptor = self._describe_at_generation(expert_id, expected)
        self._assert_current(expected, fence=fence)
        return descriptor

    def match(
        self,
        goal_text: str,
        *,
        fence: InvocationFence | None = None,
    ) -> CoreExpertSelection | None:
        if fence is not None:
            fence.check()
        expected = self._generation_pair()
        raw_match = self._registry.match(goal_text)
        if raw_match is None:
            self._assert_current(expected, fence=fence)
            return None
        match = self._validate_match(raw_match)
        descriptor = self._describe_at_generation(match[0], expected)
        self._assert_current(expected, fence=fence)
        return self._selection(match, descriptor, expected)

    def select(
        self,
        goal_text: str,
        *,
        fence: InvocationFence | None = None,
    ) -> CoreExpertSelection:
        selection = self.match(goal_text, fence=fence)
        if selection is None:
            raise CompositionError("canonical expert registry produced no symbolic match")
        return selection

    def _describe_at_generation(
        self,
        expert_id: str,
        expected: _GenerationPair,
    ) -> dict[str, Any]:
        raw_descriptor = self._registry.describe(expert_id)
        descriptor = _inert_mapping(raw_descriptor, field_name="expert descriptor")
        if self._validate_expert_id(descriptor.get("expert_id")) != expert_id:
            raise CompositionError("expert descriptor identity does not match selection")
        descriptor_generation = _builtin_nonnegative_int(
            descriptor.get("registry_generation"),
            field_name="descriptor registry generation",
        )
        if descriptor_generation != expected.registry:
            raise CompositionError("stale expert descriptor generation")
        if descriptor.get("protocol") != "ZARA-EXPERT/1":
            raise CompositionError("expert descriptor is not ZARA-EXPERT/1 compatible")
        availability = descriptor.get("availability")
        if availability not in _SELECTABLE_AVAILABILITY:
            raise CompositionError("selected expert is no longer selectable")
        return descriptor

    def _validate_match(
        self,
        raw_match: Mapping[str, Any],
    ) -> tuple[str, int, tuple[str, ...]]:
        match = _inert_mapping(raw_match, field_name="expert match")
        if set(match) != _MATCH_FIELDS:
            raise CompositionError("expert match has unexpected fields")
        expert_id = self._validate_expert_id(match.get("expert_id"))
        score = _builtin_nonnegative_int(match.get("score"), field_name="expert match score")
        if score == 0:
            raise CompositionError("expert match score must be positive")
        raw_keywords = match.get("matched_keywords")
        if not isinstance(raw_keywords, list) or not raw_keywords:
            raise CompositionError("expert match must contain matched keywords")
        keywords: list[str] = []
        seen: set[str] = set()
        for raw_keyword in raw_keywords:
            if not isinstance(raw_keyword, str) or not raw_keyword or raw_keyword != raw_keyword.strip():
                raise CompositionError("expert match keyword must be non-empty trimmed text")
            if raw_keyword in seen:
                raise CompositionError("expert match contains duplicate keywords")
            seen.add(raw_keyword)
            keywords.append(raw_keyword)
        if tuple(keywords) != tuple(sorted(keywords)):
            raise CompositionError("expert match keywords must be canonically sorted")
        return expert_id, score, tuple(keywords)

    @staticmethod
    def _selection(
        match: tuple[str, int, tuple[str, ...]],
        descriptor: Mapping[str, Any],
        expected: _GenerationPair,
    ) -> CoreExpertSelection:
        expert_id, score, keywords = match
        explanation = (
            f"canonical Zara ExpertRegistry selected {expert_id} with score {score} "
            f"from matched keywords: {', '.join(keywords)}"
        )
        return CoreExpertSelection(
            expert_id=expert_id,
            score=score,
            matched_keywords=keywords,
            registry_generation=expected.registry,
            runtime_generation=expected.runtime,
            descriptor=descriptor,
            explanation=explanation,
        )
