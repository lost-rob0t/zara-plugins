from __future__ import annotations

from typing import Any, Callable, Mapping

from .composition import (
    CompositionError,
    DelegationRequest,
    InvocationFence,
    InvocationResult,
    SharedSymbolicBudget,
)
from .dotfiles_family import EXPERT_ID


_SUPPORTED_CHILDREN = frozenset({"zara:expert/nix", "zara:expert/bash"})


def _validated_core_result(
    operation: str,
    input_data: Mapping[str, Any],
    outcome: Any,
) -> InvocationResult:
    usage = getattr(outcome, "usage", None)
    if not isinstance(usage, Mapping):
        raise CompositionError("Core DotfilesExpert result is missing usage ledger")
    model_calls = usage.get("model_calls")
    if type(model_calls) is not int or model_calls != 0:
        raise CompositionError("Core DotfilesExpert attempted model use")

    effect_receipts = getattr(outcome, "effect_receipts", None)
    if not isinstance(effect_receipts, (list, tuple)) or effect_receipts:
        raise CompositionError("Core DotfilesExpert returned unexpected effect receipts")

    data = getattr(outcome, "data", None)
    if not isinstance(data, Mapping):
        raise CompositionError("Core DotfilesExpert result data must be an object")
    nested = data.get("result")
    if not isinstance(nested, Mapping):
        raise CompositionError("Core DotfilesExpert nested result must be an object")
    nested_model_calls = nested.get("model_calls")
    if type(nested_model_calls) is not int or nested_model_calls != 0:
        raise CompositionError("Core DotfilesExpert nested result attempted model use")
    nested_receipts = nested.get("effect_receipts")
    if not isinstance(nested_receipts, (list, tuple)) or nested_receipts:
        raise CompositionError("Core DotfilesExpert nested result returned effect receipts")
    nested_data = nested.get("data")
    if not isinstance(nested_data, Mapping):
        raise CompositionError("Core DotfilesExpert nested data must be an object")

    evidence_refs = getattr(outcome, "evidence_refs", None)
    if isinstance(evidence_refs, (str, bytes)) or not isinstance(
        evidence_refs, (list, tuple)
    ):
        raise CompositionError("Core DotfilesExpert evidence_refs must be a sequence")
    evidence = tuple(str(item) for item in evidence_refs)

    raw_explanation = nested.get("explanation", ())
    if isinstance(raw_explanation, (str, bytes)) or not isinstance(
        raw_explanation, (list, tuple)
    ):
        raise CompositionError("Core DotfilesExpert explanation must be a sequence")
    explanation = " | ".join(str(item) for item in raw_explanation)
    if not explanation:
        explanation = f"{EXPERT_ID} handled {operation} through Zara Core ZARA-EXPERT/1"

    verdict = getattr(outcome, "verdict", None)
    status = getattr(verdict, "value", verdict)
    if not isinstance(status, str):
        raise CompositionError("Core DotfilesExpert result is missing verdict")

    delegations: tuple[DelegationRequest, ...] = ()
    if operation == "inspect" and status == "succeeded":
        specialist = nested_data.get("specialist_expert_id")
        language = nested_data.get("language")
        if specialist not in _SUPPORTED_CHILDREN:
            raise CompositionError("DotfilesExpert selected an unsupported child expert")
        if not isinstance(language, str) or not language:
            raise CompositionError("DotfilesExpert selected a child without a language")
        source = input_data.get("source")
        source_generation = input_data.get("source_generation")
        if not isinstance(source, str):
            raise CompositionError("DotfilesExpert inspect source must be text")
        if not isinstance(source_generation, str) or not source_generation:
            raise CompositionError("DotfilesExpert source_generation must be a reference")
        delegations = (
            DelegationRequest(
                specialist,
                "inspect",
                {
                    "source": source,
                    "source_generation": source_generation,
                },
                (
                    f"DotfilesExpert classified {nested_data.get('path')!r} as {language} "
                    f"and delegated to registered {specialist}"
                ),
            ),
        )

    return InvocationResult(
        status=status,
        data=dict(nested_data),
        evidence=evidence,
        delegations=delegations,
        explanation=explanation,
        model_calls=0,
    )


class CoreDotfilesCompositionInvoker:
    """Compose the canonical Dotfiles root with existing Core child activations.

    The caller supplies the one existing Core registry, an activation resolver,
    Core limits factory, and the already-existing child invoker. This adapter owns
    none of those authorities and never creates a parallel registry or budget.
    """

    def __init__(
        self,
        registry: Any,
        *,
        activation_for: Callable[[str, InvocationFence], Any],
        limits_factory: Callable[..., Any],
        child_invoker: Callable[..., InvocationResult],
    ) -> None:
        if not callable(getattr(registry, "invoke", None)):
            raise TypeError("Core Dotfiles composition requires a registry with invoke()")
        if not callable(activation_for):
            raise TypeError("activation_for must be callable")
        if not callable(limits_factory):
            raise TypeError("limits_factory must be callable")
        if not callable(child_invoker):
            raise TypeError("child_invoker must be callable")
        self._registry = registry
        self._activation_for = activation_for
        self._limits_factory = limits_factory
        self._child_invoker = child_invoker

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
        if expert_id != EXPERT_ID:
            return self._child_invoker(
                expert_id,
                operation,
                input_data,
                budget=budget,
                fence=fence,
                parent_path=parent_path,
            )

        budget.assert_zero_model_usage()
        fence.check()
        if not isinstance(input_data, Mapping):
            raise CompositionError("DotfilesExpert input must be an object")

        try:
            handle = self._activation_for(expert_id, fence)
        except Exception as exc:
            raise CompositionError(
                f"canonical Core Dotfiles activation resolution failed: {exc}"
            ) from exc
        if getattr(handle, "expert_id", None) != EXPERT_ID:
            raise CompositionError("canonical Core Dotfiles activation identity mismatch")
        if getattr(handle, "workspace", None) != fence.workspace_id:
            raise CompositionError("canonical Core Dotfiles activation workspace mismatch")

        fence.check()
        budget.assert_zero_model_usage()
        try:
            limits = self._limits_factory(max_model_calls=budget.max_model_calls)
            outcome = self._registry.invoke(
                handle,
                operation,
                dict(input_data),
                limits=limits,
            )
        except Exception as exc:
            raise CompositionError(
                f"canonical Core Dotfiles invocation failed: {exc}"
            ) from exc

        fence.check()
        budget.assert_zero_model_usage()
        return _validated_core_result(operation, input_data, outcome)


__all__ = ["CoreDotfilesCompositionInvoker"]
