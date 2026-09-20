from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import PurePosixPath
import re
from typing import Any, Callable, Mapping, Protocol, Sequence


class CompositionError(RuntimeError):
    """Fail-closed error for symbolic expert composition."""


_TERMINAL_STATUSES = {
    "succeeded",
    "failed",
    "unknown",
    "blocked",
    "unsupported",
    "cancelled",
    "error",
}


@dataclass(frozen=True)
class DelegationRequest:
    expert_id: str
    operation: str
    input: Mapping[str, Any]
    reason: str


@dataclass(frozen=True)
class InvocationResult:
    status: str
    data: Mapping[str, Any] = field(default_factory=dict)
    evidence: tuple[str, ...] = ()
    delegations: tuple[DelegationRequest, ...] = ()
    explanation: str = ""
    model_calls: int = 0

    def __post_init__(self) -> None:
        if self.status not in _TERMINAL_STATUSES:
            raise CompositionError(f"invalid expert status: {self.status!r}")
        if isinstance(self.model_calls, bool) or not isinstance(self.model_calls, int):
            raise CompositionError("model_calls must be an integer")
        if self.model_calls != 0:
            raise CompositionError("pure symbolic expert attempted model use")


@dataclass
class SharedSymbolicBudget:
    max_invocations: int = 16
    max_depth: int = 8
    max_evidence: int = 64
    max_model_calls: int = 0
    invocations_used: int = 0
    evidence_used: int = 0
    model_calls_used: int = 0

    def __post_init__(self) -> None:
        for name in ("max_invocations", "max_depth", "max_evidence"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.max_invocations == 0:
            raise ValueError("max_invocations must be positive")
        if self.max_evidence == 0:
            raise ValueError("max_evidence must be positive")
        if self.max_model_calls != 0:
            raise ValueError("pure symbolic composition requires max_model_calls=0")

    def admit(self, depth: int) -> None:
        if depth > self.max_depth:
            raise CompositionError("expert delegation depth budget exceeded")
        if self.invocations_used >= self.max_invocations:
            raise CompositionError("expert invocation budget exceeded")
        self.invocations_used += 1

    def record_evidence(self, count: int) -> None:
        if count < 0:
            raise ValueError("evidence count must be non-negative")
        if self.evidence_used + count > self.max_evidence:
            raise CompositionError("expert evidence budget exceeded")
        self.evidence_used += count


@dataclass(frozen=True)
class InvocationFence:
    workspace_id: str
    workspace_generation: int
    is_cancelled: Callable[[], bool]
    is_current_generation: Callable[[str, int], bool]

    def check(self) -> None:
        if self.is_cancelled():
            raise CompositionError("expert invocation cancelled")
        if not self.is_current_generation(self.workspace_id, self.workspace_generation):
            raise CompositionError("stale workspace generation")


@dataclass(frozen=True)
class EvidenceNode:
    expert_id: str
    operation: str
    status: str
    reason: str
    evidence: tuple[str, ...]
    explanation: str
    children: tuple["EvidenceNode", ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "expert_id": self.expert_id,
            "operation": self.operation,
            "status": self.status,
            "reason": self.reason,
            "evidence": list(self.evidence),
            "explanation": self.explanation,
            "children": [child.as_dict() for child in self.children],
        }


class SymbolicInvoker(Protocol):
    def __call__(
        self,
        expert_id: str,
        operation: str,
        input_data: Mapping[str, Any],
        *,
        budget: SharedSymbolicBudget,
        fence: InvocationFence,
        parent_path: tuple[str, ...],
    ) -> InvocationResult: ...


class ExpertCatalogAdapter:
    """Read-only facade over Zara's canonical expert registry operations."""

    def __init__(
        self,
        *,
        list_experts: Callable[[], Sequence[Mapping[str, Any]]],
        describe_expert: Callable[[str], Mapping[str, Any]],
        match_experts: Callable[[Mapping[str, Any]], Sequence[Mapping[str, Any]]],
    ) -> None:
        self._list = list_experts
        self._describe = describe_expert
        self._match = match_experts

    def list(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._list())

    def describe(self, expert_id: str) -> Mapping[str, Any]:
        return self._describe(expert_id)

    def match(self, request: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._match(request))


class HostExpertInvoker:
    """Adapter from canonical expert identity to the existing zara-expert host."""

    def __init__(
        self,
        host: Any,
        *,
        namespace_for_id: Callable[[str], str],
    ) -> None:
        self._host = host
        self._namespace_for_id = namespace_for_id

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
        del budget, parent_path
        fence.check()
        namespace = self._namespace_for_id(expert_id)
        goal = input_data.get("goal")
        if not isinstance(goal, str):
            raise CompositionError("zara-expert host invocation requires text goal")
        if operation == "query":
            raw = self._host.query(namespace, goal)
        elif operation == "explain":
            raw = self._host.explain(namespace, goal)
        else:
            raise CompositionError(f"unsupported zara-expert host operation: {operation}")
        fence.check()
        evidence = tuple(str(item) for item in raw.get("trace", ()))
        return InvocationResult(
            status="succeeded" if raw.get("ok", False) else "failed",
            data={"results": raw.get("results", ())},
            evidence=evidence,
            explanation=f"{expert_id} handled {operation} through zara-expert",
            model_calls=0,
        )


_PACKAGE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


@dataclass(frozen=True)
class ProjectExpertResource:
    workspace_id: str
    workspace_generation: int
    package: str
    relative_path: str
    source_reference: str
    content: str


class DotfilesExpertSourceAdapter:
    """Transport-neutral reader for the canonical project `.zara/experts/` tree."""

    ROOT = ".zara/experts"

    def __init__(
        self,
        *,
        list_package_names: Callable[[str, int], Sequence[str]],
        read_package_text: Callable[[str, int, str, str], str],
    ) -> None:
        self._list_package_names = list_package_names
        self._read_package_text = read_package_text

    def list_packages(self, *, fence: InvocationFence) -> tuple[str, ...]:
        fence.check()
        names = tuple(self._list_package_names(
            fence.workspace_id,
            fence.workspace_generation,
        ))
        normalized: list[str] = []
        folded: set[str] = set()
        for name in names:
            if not isinstance(name, str) or not _PACKAGE_NAME_RE.fullmatch(name):
                raise CompositionError(f"invalid project expert package name: {name!r}")
            key = name.casefold()
            if key in folded:
                raise CompositionError(f"duplicate project expert package name: {name!r}")
            folded.add(key)
            normalized.append(name)
        fence.check()
        return tuple(sorted(normalized))

    def read_resource(
        self,
        package: str,
        relative_path: str,
        *,
        fence: InvocationFence,
    ) -> ProjectExpertResource:
        if not isinstance(package, str) or not _PACKAGE_NAME_RE.fullmatch(package):
            raise CompositionError("invalid project expert package name")
        path = self._validate_relative_path(relative_path)
        fence.check()
        content = self._read_package_text(
            fence.workspace_id,
            fence.workspace_generation,
            package,
            path,
        )
        fence.check()
        if not isinstance(content, str):
            raise CompositionError("project expert resource must be text")
        return ProjectExpertResource(
            workspace_id=fence.workspace_id,
            workspace_generation=fence.workspace_generation,
            package=package,
            relative_path=path,
            source_reference=f"{self.ROOT}/{package}/{path}",
            content=content,
        )

    @staticmethod
    def _validate_relative_path(relative_path: str) -> str:
        if not isinstance(relative_path, str) or not relative_path:
            raise CompositionError("project expert resource path must be relative text")
        path = PurePosixPath(relative_path)
        if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
            raise CompositionError("project expert resource path escapes package")
        normalized = str(path)
        if normalized.startswith("../") or "/../" in normalized:
            raise CompositionError("project expert resource path escapes package")
        return normalized


class MetaExpertComposer:
    """Immediate bounded composition; lifecycle/scheduling remain owned by Zara."""

    def __init__(self, invoker: SymbolicInvoker) -> None:
        self._invoker = invoker

    def invoke(
        self,
        expert_id: str,
        operation: str,
        input_data: Mapping[str, Any],
        *,
        budget: SharedSymbolicBudget,
        fence: InvocationFence,
    ) -> EvidenceNode:
        return self._invoke(
            expert_id,
            operation,
            input_data,
            budget=budget,
            fence=fence,
            path=(),
            reason="root selection",
        )

    def _invoke(
        self,
        expert_id: str,
        operation: str,
        input_data: Mapping[str, Any],
        *,
        budget: SharedSymbolicBudget,
        fence: InvocationFence,
        path: tuple[str, ...],
        reason: str,
    ) -> EvidenceNode:
        fence.check()
        if expert_id in path:
            chain = " -> ".join((*path, expert_id))
            raise CompositionError(f"expert delegation cycle: {chain}")
        next_path = (*path, expert_id)
        budget.admit(len(path))
        result = self._invoker(
            expert_id,
            operation,
            input_data,
            budget=budget,
            fence=fence,
            parent_path=path,
        )
        fence.check()
        if result.model_calls != 0:
            raise CompositionError("pure symbolic expert attempted model use")
        budget.record_evidence(len(result.evidence))

        children = []
        for child in result.delegations:
            fence.check()
            children.append(
                self._invoke(
                    child.expert_id,
                    child.operation,
                    child.input,
                    budget=budget,
                    fence=fence,
                    path=next_path,
                    reason=child.reason,
                )
            )
        fence.check()
        return EvidenceNode(
            expert_id=expert_id,
            operation=operation,
            status=result.status,
            reason=reason,
            evidence=result.evidence,
            explanation=result.explanation,
            children=tuple(children),
        )


class StyleScope(IntEnum):
    LIBRARY_DEFAULT = 0
    USER_GLOBAL = 1
    USER_LANGUAGE = 2
    PROJECT_GLOBAL = 3
    PROJECT_LANGUAGE = 4
    SESSION = 5


_FORBIDDEN_STYLE_KEYS = frozenset(
    {"authority", "capabilities", "permissions", "required_capabilities"}
)


@dataclass(frozen=True)
class StyleOverlay:
    scope: StyleScope
    values: Mapping[str, Any]
    source: str
    revision: str
    language: str | None = None
    workspace_id: str | None = None
    workspace_generation: int | None = None

    def __post_init__(self) -> None:
        forbidden = _FORBIDDEN_STYLE_KEYS.intersection(self.values)
        if forbidden:
            names = ", ".join(sorted(forbidden))
            raise CompositionError(f"style overlay cannot change authority: {names}")
        if self.scope in (StyleScope.USER_LANGUAGE, StyleScope.PROJECT_LANGUAGE):
            if not self.language:
                raise CompositionError("language-scoped style overlay requires language")
        if self.scope in (StyleScope.PROJECT_GLOBAL, StyleScope.PROJECT_LANGUAGE):
            if not self.workspace_id or self.workspace_generation is None:
                raise CompositionError("project style overlay requires workspace generation")


@dataclass(frozen=True)
class EffectiveStyle:
    values: Mapping[str, Any]
    provenance: Mapping[str, tuple[str, str, str]]


def resolve_style(
    overlays: Sequence[StyleOverlay],
    *,
    language: str | None,
    fence: InvocationFence,
) -> EffectiveStyle:
    """Apply canonical precedence without executing expert code or widening authority."""

    applicable: list[tuple[int, int, StyleOverlay]] = []
    for ordinal, overlay in enumerate(overlays):
        if overlay.language is not None and overlay.language != language:
            continue
        if overlay.scope in (StyleScope.PROJECT_GLOBAL, StyleScope.PROJECT_LANGUAGE):
            if overlay.workspace_id != fence.workspace_id:
                continue
            if overlay.workspace_generation != fence.workspace_generation:
                raise CompositionError("stale project style generation")
        applicable.append((int(overlay.scope), ordinal, overlay))

    fence.check()
    values: dict[str, Any] = {}
    provenance: dict[str, tuple[str, str, str]] = {}
    for _, _, overlay in sorted(applicable, key=lambda item: (item[0], item[1])):
        for key, value in overlay.values.items():
            values[key] = value
            provenance[key] = (overlay.scope.name.lower(), overlay.source, overlay.revision)
    fence.check()
    return EffectiveStyle(values=values, provenance=provenance)
