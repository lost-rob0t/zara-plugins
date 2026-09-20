from __future__ import annotations

from typing import Any, Mapping

from .composition import (
    CompositionError,
    InvocationFence,
    InvocationResult,
    SharedSymbolicBudget,
)
from .domain import ExpertError, ExpertHost
from .language_family import language_family_specs
from .language_handler import make_language_expert_handler


_LANGUAGE_EXPERT_IDS = frozenset(spec.expert_id for spec in language_family_specs())


class LanguageFamilyCompositionInvoker:
    """Bridge language experts into Zara's canonical symbolic composer.

    This bridge owns no registry, scheduler, provider runtime, permission state,
    or usage ledger. It invokes the existing Core-facing language handler under
    the caller-owned shared zero-model budget and cancellation/workspace fence.
    """

    def __init__(self, host: ExpertHost) -> None:
        self._host = host

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

        if expert_id not in _LANGUAGE_EXPERT_IDS:
            raise CompositionError(f"unsupported language expert: {expert_id!r}")
        if not isinstance(input_data, Mapping):
            raise CompositionError("language expert input must be an object")

        payload: dict[str, Any] = {}
        for key, value in input_data.items():
            if not isinstance(key, str):
                raise CompositionError("language expert input keys must be text")
            payload[key] = value

        handler = make_language_expert_handler(self._host, expert_id)
        try:
            outcome = handler(expert_operation=operation, **payload)
        except ExpertError as exc:
            raise CompositionError(str(exc)) from exc

        fence.check()
        budget.assert_zero_model_usage()
        if not isinstance(outcome, Mapping):
            raise CompositionError("language expert handler returned non-object result")

        usage = outcome.get("usage")
        if not isinstance(usage, Mapping):
            raise CompositionError("language expert result is missing usage ledger")
        model_calls = usage.get("model_calls")
        if type(model_calls) is not int or model_calls != 0:
            raise CompositionError("language expert attempted model use")

        effect_receipts = outcome.get("effect_receipts")
        if not isinstance(effect_receipts, (list, tuple)) or effect_receipts:
            raise CompositionError("language expert returned unexpected effect receipts")

        data = outcome.get("data", {})
        if not isinstance(data, Mapping):
            raise CompositionError("language expert result data must be an object")

        evidence: tuple[str, ...] = ()
        explanation = f"{expert_id} handled {operation} through the registered language expert host"
        nested = data.get("result")
        if nested is not None:
            if not isinstance(nested, Mapping):
                raise CompositionError("language expert nested result must be an object")
            nested_model_calls = nested.get("model_calls")
            if type(nested_model_calls) is not int or nested_model_calls != 0:
                raise CompositionError("language expert nested result attempted model use")
            nested_receipts = nested.get("effect_receipts")
            if not isinstance(nested_receipts, (list, tuple)) or nested_receipts:
                raise CompositionError("language expert nested result returned effect receipts")
            raw_evidence = nested.get("evidence", ())
            if isinstance(raw_evidence, (str, bytes)) or not isinstance(
                raw_evidence, (list, tuple)
            ):
                raise CompositionError("language expert evidence must be a sequence")
            evidence = tuple(str(item) for item in raw_evidence)
            raw_explanation = nested.get("explanation", ())
            if isinstance(raw_explanation, (str, bytes)) or not isinstance(
                raw_explanation, (list, tuple)
            ):
                raise CompositionError("language expert explanation must be a sequence")
            if raw_explanation:
                explanation = " | ".join(str(item) for item in raw_explanation)

        status = outcome.get("verdict")
        if not isinstance(status, str):
            raise CompositionError("language expert result is missing verdict")
        return InvocationResult(
            status=status,
            data=dict(data),
            evidence=evidence,
            explanation=explanation,
            model_calls=0,
        )


__all__ = ["LanguageFamilyCompositionInvoker"]
