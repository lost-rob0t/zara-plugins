from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .composition import (
    CompositionError,
    EvidenceNode,
    InvocationFence,
    InvocationResult,
    MetaExpertComposer,
    SharedSymbolicBudget,
)
from .core_catalog import CoreExpertCatalogAdapter, CoreExpertSelection


@dataclass(frozen=True)
class CoreCatalogCompositionResult:
    selection: CoreExpertSelection
    evidence: EvidenceNode
    explanation: str


class CoreCatalogSelectedChildInvoker:
    """Validate a delegated child against canonical Core discovery before dispatch.

    The parent expert remains responsible for deciding that delegation is needed.
    This adapter only proves that the delegated identity is still the expert selected
    by Zara Core's existing registry for a deterministic symbolic goal, preserves the
    canonical selection explanation, and rejects late evidence if that selection
    drifts while the child is running.
    """

    def __init__(
        self,
        catalog: CoreExpertCatalogAdapter,
        invoker: Callable[..., InvocationResult],
        *,
        goal_for: Callable[[str, str, Mapping[str, Any]], str],
    ) -> None:
        if not isinstance(catalog, CoreExpertCatalogAdapter):
            raise TypeError("catalog must be CoreExpertCatalogAdapter")
        if not callable(invoker):
            raise TypeError("invoker must be callable")
        if not callable(goal_for):
            raise TypeError("goal_for must be callable")
        self._catalog = catalog
        self._invoker = invoker
        self._goal_for = goal_for

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
        budget.assert_zero_model_usage()
        fence.check()
        goal_text = self._goal_for(expert_id, operation, input_data)
        if not isinstance(goal_text, str) or not goal_text.strip():
            raise CompositionError("delegated catalog goal must be non-empty text")

        selection = self._catalog.select(goal_text, fence=fence)
        CoreCatalogCompositionAdapter._require_zero_model_descriptor(selection)
        if selection.expert_id != expert_id:
            raise CompositionError(
                "canonical catalog selection disagrees with delegated expert"
            )

        result = self._invoker(
            expert_id,
            operation,
            input_data,
            budget=budget,
            fence=fence,
            parent_path=parent_path,
        )
        if not isinstance(result, InvocationResult):
            raise CompositionError("delegated child invoker returned invalid result")

        fence.check()
        budget.assert_zero_model_usage()
        current = self._catalog.select(goal_text, fence=fence)
        if current != selection:
            raise CompositionError("stale canonical delegated expert selection")
        if current.expert_id != expert_id:
            raise CompositionError(
                "canonical catalog selection disagrees with delegated expert"
            )

        explanation = selection.explanation
        if result.explanation:
            explanation = f"{explanation}; {result.explanation}"
        return InvocationResult(
            status=result.status,
            data=result.data,
            evidence=result.evidence,
            delegations=result.delegations,
            explanation=explanation,
            model_calls=result.model_calls,
        )


class CoreCatalogCompositionAdapter:
    """Bind canonical Core discovery to the existing symbolic composer.

    This adapter owns no registry, activation, scheduler, provider runtime, or
    budget. It only preserves the canonical catalog selection across the
    existing ``MetaExpertComposer`` call and rejects the result if the Core
    registry/runtime generation or selected descriptor changes before evidence
    can be returned.
    """

    def __init__(
        self,
        catalog: CoreExpertCatalogAdapter,
        composer: MetaExpertComposer,
    ) -> None:
        if not isinstance(catalog, CoreExpertCatalogAdapter):
            raise TypeError("catalog must be CoreExpertCatalogAdapter")
        if not isinstance(composer, MetaExpertComposer):
            raise TypeError("composer must be MetaExpertComposer")
        self._catalog = catalog
        self._composer = composer

    def invoke(
        self,
        goal_text: str,
        operation: str,
        input_data: Mapping[str, Any],
        *,
        budget: SharedSymbolicBudget,
        fence: InvocationFence,
    ) -> CoreCatalogCompositionResult:
        budget.assert_zero_model_usage()
        fence.check()

        selection = self._catalog.select(goal_text, fence=fence)
        self._require_zero_model_descriptor(selection)
        self._assert_selection_current(goal_text, selection, fence=fence)

        evidence = self._composer.invoke(
            selection.expert_id,
            operation,
            input_data,
            budget=budget,
            fence=fence,
        )

        fence.check()
        budget.assert_zero_model_usage()
        self._assert_selection_current(goal_text, selection, fence=fence)
        explanation = f"{selection.explanation}; {evidence.explanation}"
        return CoreCatalogCompositionResult(
            selection=selection,
            evidence=evidence,
            explanation=explanation,
        )

    def _assert_selection_current(
        self,
        goal_text: str,
        expected: CoreExpertSelection,
        *,
        fence: InvocationFence,
    ) -> None:
        current = self._catalog.select(goal_text, fence=fence)
        if current != expected:
            raise CompositionError("stale canonical expert selection")

    @staticmethod
    def _require_zero_model_descriptor(selection: CoreExpertSelection) -> None:
        limits = selection.descriptor.get("resource_limits")
        if not isinstance(limits, Mapping):
            raise CompositionError("selected expert is missing resource_limits")
        max_model_calls = limits.get("max_model_calls")
        if type(max_model_calls) is not int or max_model_calls != 0:
            raise CompositionError(
                "pure symbolic catalog composition requires descriptor max_model_calls=0"
            )


__all__ = [
    "CoreCatalogCompositionAdapter",
    "CoreCatalogCompositionResult",
    "CoreCatalogSelectedChildInvoker",
]
