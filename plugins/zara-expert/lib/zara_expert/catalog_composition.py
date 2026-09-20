from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .composition import (
    CompositionError,
    EvidenceNode,
    InvocationFence,
    MetaExpertComposer,
    SharedSymbolicBudget,
)
from .core_catalog import CoreExpertCatalogAdapter, CoreExpertSelection


@dataclass(frozen=True)
class CoreCatalogCompositionResult:
    selection: CoreExpertSelection
    evidence: EvidenceNode
    explanation: str


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


__all__ = ["CoreCatalogCompositionAdapter", "CoreCatalogCompositionResult"]
