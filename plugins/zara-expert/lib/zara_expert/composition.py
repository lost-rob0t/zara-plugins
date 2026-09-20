from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
import json
from pathlib import PurePosixPath
import re
from typing import Any, Callable, Mapping, Protocol, Sequence


class CompositionError(RuntimeError):
    """Fail-closed error for pure-symbolic expert composition."""


_TERMINAL_STATUSES = {
    "succeeded",
    "failed",
    "unknown",
    "blocked",
    "unsupported",
    "cancelled",
    "error",
}
_JSON_SCALARS = (str, int, float, bool, type(None))
_PACKAGE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_FORBIDDEN_STYLE_KEYS = frozenset(
    {"authority", "capabilities", "permissions", "required_capabilities"}
)
_BUDGET_FIELDS = (
    "max_invocations",
    "max_depth",
    "max_evidence",
    "max_model_calls",
    "invocations_used",
    "evidence_used",
    "model_calls_used",
)


def _normalized_inert_value(value: Any) -> Any:
    """Return a deterministic JSON-like value or fail before expert dispatch."""

    if isinstance(value, _JSON_SCALARS):
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CompositionError("expert input mapping keys must be text")
            normalized[key] = _normalized_inert_value(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalized_inert_value(item) for item in value]
    raise CompositionError(f"expert input contains unsupported value: {type(value).__name__}")


def _invocation_signature(
    expert_id: str,
    operation: str,
    input_data: Mapping[str, Any],
) -> tuple[str, str, str]:
    inert = _normalized_inert_value(input_data)
    encoded = json.dumps(inert, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return expert_id, operation, encoded


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
        _normalized_inert_value(self.data)
        for delegation in self.delegations:
            _normalized_inert_value(delegation.input)


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
        self._assert_integrity()
        self.assert_zero_model_usage()

    def _assert_integrity(self) -> None:
        for name in _BUDGET_FIELDS:
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.max_invocations == 0:
            raise ValueError("max_invocations must be positive")
        if self.max_evidence == 0:
            raise ValueError("max_evidence must be positive")

    def snapshot(self) -> tuple[tuple[str, int], ...]:
        self._assert_integrity()
        self.assert_zero_model_usage()
        return tuple((name, getattr(self, name)) for name in _BUDGET_FIELDS)

    def assert_unchanged_by_invoker(
        self,
        snapshot: tuple[tuple[str, int], ...],
    ) -> None:
        expected = dict(snapshot)
        current_state = vars(self)
        changed: list[str] = []
        for name in _BUDGET_FIELDS:
            wanted = expected[name]
            if name not in current_state:
                changed.append(name)
                continue
            current = current_state[name]
            if type(current) is not int or current != wanted:
                changed.append(name)
        unexpected = sorted(set(current_state) - set(_BUDGET_FIELDS))
        changed.extend(f"attribute:{name}" for name in unexpected)
        if not changed:
            return
        for name in unexpected:
            delattr(self, name)
        for name in _BUDGET_FIELDS:
            setattr(self, name, expected[name])
        names = ", ".join(changed)
        raise CompositionError(f"expert invoker mutated shared symbolic budget: {names}")

    def assert_zero_model_usage(self) -> None:
        if type(self.max_model_calls) is not int or self.max_model_calls != 0:
            raise ValueError("pure symbolic composition requires max_model_calls=0")
        if type(self.model_calls_used) is not int or self.model_calls_used != 0:
            raise CompositionError("pure symbolic model-call ledger is nonzero")

    def admit(self, depth: int) -> None:
        self._assert_integrity()
        self.assert_zero_model_usage()
        if depth > self.max_depth:
            raise CompositionError("expert delegation depth budget exceeded")
        if self.invocations_used >= self.max_invocations:
            raise CompositionError("expert invocation budget exceeded")
        self.invocations_used += 1

    def record_evidence(self, count: int) -> None:
        self._assert_integrity()
        self.assert_zero_model_usage()
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("evidence count must be a non-negative integer")
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
    data: Mapping[str, Any]
    evidence: tuple[str, ...]
    explanation: str
    children: tuple["EvidenceNode", ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "expert_id": self.expert_id,
            "operation": self.operation,
            "status": self.status,
            "reason": self.reason,
            "data": dict(self.data),
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
        _normalized_inert_value(request)
        return tuple(self._match(request))


@dataclass(frozen=True)
class RegisteredPredicateBinding:
    """Trusted private binding resolved from Zara's canonical expert registration."""

    namespace: str
    predicate: str
    arguments: tuple[Any, ...]
    host_operation: str = "query"

    def __post_init__(self) -> None:
        if self.host_operation not in ("query", "explain"):
            raise CompositionError("registered predicate binding operation must be query or explain")
        _normalized_inert_value(self.arguments)


class HostExpertInvoker:
    """Adapter to zara-expert's host-issued registered-predicate authority boundary.

    Invocation data never selects a Prolog predicate. A trusted resolver owned by
    canonical registration maps expert identity + operation + inert input to the
    already-registered namespace/predicate/argument tuple.
    """

    def __init__(
        self,
        host: Any,
        *,
        binding_for: Callable[[str, str, Mapping[str, Any]], RegisteredPredicateBinding],
    ) -> None:
        self._host = host
        self._binding_for = binding_for

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
        inert_input = _normalized_inert_value(input_data)
        binding = self._binding_for(expert_id, operation, inert_input)
        if not isinstance(binding, RegisteredPredicateBinding):
            raise CompositionError("trusted expert binding resolver returned invalid binding")
        if binding.host_operation == "query":
            raw = self._host.query(binding.namespace, binding.predicate, binding.arguments)
        else:
            raw = self._host.explain(binding.namespace, binding.predicate, binding.arguments)
        fence.check()
        budget.assert_zero_model_usage()
        if not isinstance(raw, Mapping):
            raise CompositionError("zara-expert host returned non-object result")
        results = raw.get("results", ())
        trace = raw.get("trace", ())
        evidence = tuple(str(item) for item in trace)
        ok = raw.get("ok")
        if ok is True:
            status = "succeeded"
        elif ok is False:
            status = "failed"
        else:
            status = "unknown"
        return InvocationResult(
            status=status,
            data={"results": _normalized_inert_value(results)},
            evidence=evidence,
            explanation=(
                f"{expert_id} handled {operation} through registered "
                f"{binding.namespace}:{binding.predicate}"
            ),
            model_calls=0,
        )


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
        names = tuple(
            self._list_package_names(fence.workspace_id, fence.workspace_generation)
        )
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
        budget.assert_zero_model_usage()
        return self._invoke(
            expert_id,
            operation,
            input_data,
            budget=budget,
            fence=fence,
            signatures=(),
            labels=(),
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
        signatures: tuple[tuple[str, str, str], ...],
        labels: tuple[str, ...],
        reason: str,
    ) -> EvidenceNode:
        fence.check()
        budget.assert_zero_model_usage()
        signature = _invocation_signature(expert_id, operation, input_data)
        label = f"{expert_id}.{operation}"
        if signature in signatures:
            chain = " -> ".join((*labels, label))
            raise CompositionError(f"expert delegation made no progress: {chain}")
        next_signatures = (*signatures, signature)
        next_labels = (*labels, label)
        budget.admit(len(signatures))
        budget_snapshot = budget.snapshot()
        try:
            result = self._invoker(
                expert_id,
                operation,
                _normalized_inert_value(input_data),
                budget=budget,
                fence=fence,
                parent_path=labels,
            )
        finally:
            SharedSymbolicBudget.assert_unchanged_by_invoker(budget, budget_snapshot)
        fence.check()
        budget.assert_zero_model_usage()
        if result.model_calls != 0:
            raise CompositionError("pure symbolic expert attempted model use")
        budget.record_evidence(len(result.evidence))

        children = []
        for child in result.delegations:
            fence.check()
            budget.assert_zero_model_usage()
            children.append(
                self._invoke(
                    child.expert_id,
                    child.operation,
                    child.input,
                    budget=budget,
                    fence=fence,
                    signatures=next_signatures,
                    labels=next_labels,
                    reason=child.reason,
                )
            )
        fence.check()
        budget.assert_zero_model_usage()
        return EvidenceNode(
            expert_id=expert_id,
            operation=operation,
            status=result.status,
            reason=reason,
            data=result.data,
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
        _normalized_inert_value(self.values)
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
        if self.scope is StyleScope.SESSION:
            if not self.workspace_id or self.workspace_generation is None:
                raise CompositionError("session style overlay requires workspace generation")


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
        if overlay.scope is StyleScope.SESSION:
            if overlay.workspace_id != fence.workspace_id:
                continue
            if overlay.workspace_generation != fence.workspace_generation:
                raise CompositionError("stale session style generation")
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
