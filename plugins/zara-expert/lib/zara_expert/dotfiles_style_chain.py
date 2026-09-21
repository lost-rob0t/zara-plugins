from __future__ import annotations

from typing import Callable, Mapping

from .composition import (
    CompositionError,
    DelegationRequest,
    InvocationFence,
    InvocationResult,
    SharedSymbolicBudget,
)
from .dotfiles_style_expert import STYLE_EXPERT_ID


_LANGUAGE_BY_EXPERT = {
    "zara:expert/nix": "nix",
    "zara:expert/bash": "bash",
}


class DotfilesStyleLanguageChainInvoker:
    """Compose canonical Nix/Bash children into the Dotfiles-owned StyleExpert.

    This is a fixed product adapter, not a registry. Nix/Bash dispatch remains
    owned by the caller-supplied canonical Core/catalog invoker, StyleExpert
    dispatch remains owned by the caller-supplied registered-predicate adapter,
    and MetaExpertComposer remains the sole invocation/evidence budget owner.
    """

    def __init__(
        self,
        language_invoker: Callable[..., InvocationResult],
        style_invoker: Callable[..., InvocationResult],
    ) -> None:
        if not callable(language_invoker):
            raise TypeError("language_invoker must be callable")
        if not callable(style_invoker):
            raise TypeError("style_invoker must be callable")
        self._language_invoker = language_invoker
        self._style_invoker = style_invoker

    def __call__(
        self,
        expert_id: str,
        operation: str,
        input_data: Mapping[str, object],
        *,
        budget: SharedSymbolicBudget,
        fence: InvocationFence,
        parent_path: tuple[str, ...],
    ) -> InvocationResult:
        budget.assert_zero_model_usage()
        fence.check()

        if expert_id == STYLE_EXPERT_ID:
            result = self._style_invoker(
                expert_id,
                operation,
                input_data,
                budget=budget,
                fence=fence,
                parent_path=parent_path,
            )
            return self._validated_result(result, budget=budget, fence=fence)

        language = _LANGUAGE_BY_EXPERT.get(expert_id)
        if language is None:
            raise CompositionError(
                f"unsupported Dotfiles style-chain expert: {expert_id!r}"
            )

        result = self._language_invoker(
            expert_id,
            operation,
            input_data,
            budget=budget,
            fence=fence,
            parent_path=parent_path,
        )
        result = self._validated_result(result, budget=budget, fence=fence)
        if operation != "inspect" or result.status != "succeeded":
            return result

        if any(child.expert_id == STYLE_EXPERT_ID for child in result.delegations):
            raise CompositionError("language expert returned duplicate StyleExpert delegation")

        style_delegation = DelegationRequest(
            expert_id=STYLE_EXPERT_ID,
            operation="resolve",
            input={"language": language},
            reason=(
                f"{language.title()}Expert inspect succeeded; "
                "resolve canonical Dotfiles style"
            ),
        )
        return InvocationResult(
            status=result.status,
            data=result.data,
            evidence=result.evidence,
            delegations=(*result.delegations, style_delegation),
            explanation=result.explanation,
            model_calls=0,
        )

    @staticmethod
    def _validated_result(
        result: InvocationResult,
        *,
        budget: SharedSymbolicBudget,
        fence: InvocationFence,
    ) -> InvocationResult:
        fence.check()
        budget.assert_zero_model_usage()
        if not isinstance(result, InvocationResult):
            raise CompositionError("Dotfiles style-chain invoker returned invalid result")
        if result.model_calls != 0:
            raise CompositionError("Dotfiles style-chain child attempted model use")
        return result


__all__ = ["DotfilesStyleLanguageChainInvoker"]
