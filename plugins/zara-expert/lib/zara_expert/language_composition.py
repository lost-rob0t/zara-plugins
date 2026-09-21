from __future__ import annotations

from typing import Any, Callable, Mapping

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
_TYPED_EXPERT_IDS = frozenset(
    {
        "zara:expert/prolog",
        "zara:expert/python",
        "zara:expert/nim",
        "zara:expert/javascript",
        "zara:expert/typescript",
        "zara:expert/java",
        "zara:expert/kotlin",
    }
)


def _validated_language_payload(
    expert_id: str,
    input_data: Mapping[str, Any],
) -> dict[str, Any]:
    if expert_id not in _LANGUAGE_EXPERT_IDS:
        raise CompositionError(f"unsupported language expert: {expert_id!r}")
    if not isinstance(input_data, Mapping):
        raise CompositionError("language expert input must be an object")

    payload: dict[str, Any] = {}
    for key, value in input_data.items():
        if not isinstance(key, str):
            raise CompositionError("language expert input keys must be text")
        payload[key] = value
    return payload


def _validated_evidence_refs(raw: Any, *, source: str) -> tuple[str, ...]:
    if isinstance(raw, (str, bytes)) or not isinstance(raw, (list, tuple)):
        raise CompositionError(f"{source} evidence_refs must be a sequence")
    return tuple(str(item) for item in raw)


def _typed_explanation(
    expert_id: str,
    operation: str,
    status: str,
    data: Mapping[str, Any],
    *,
    route: str,
) -> str:
    explanation = f"{expert_id} handled {operation} through {route}"
    if expert_id not in _TYPED_EXPERT_IDS or operation != "explain" or status != "succeeded":
        return explanation

    payload = data.get("explanation")
    if not isinstance(payload, Mapping):
        raise CompositionError("typed language explanation must be an object")
    raw_trace = payload.get("trace", ())
    if isinstance(raw_trace, (str, bytes)) or not isinstance(raw_trace, (list, tuple)):
        raise CompositionError("typed language explanation trace must be a sequence")
    raw_terms = payload.get("symbolic_terms", ())
    if isinstance(raw_terms, (str, bytes)) or not isinstance(raw_terms, (list, tuple)):
        raise CompositionError("typed language explanation terms must be a sequence")

    rendered = tuple(str(item) for item in raw_trace) or tuple(
        str(item) for item in raw_terms
    )
    if rendered:
        explanation = f"{explanation}: {' | '.join(rendered)}"
    return explanation


def _validated_core_result(
    expert_id: str,
    operation: str,
    outcome: Any,
) -> InvocationResult:
    usage = getattr(outcome, "usage", None)
    if not isinstance(usage, Mapping):
        raise CompositionError("Core expert result is missing usage ledger")
    model_calls = usage.get("model_calls")
    if type(model_calls) is not int or model_calls != 0:
        raise CompositionError("Core language expert attempted model use")

    effect_receipts = getattr(outcome, "effect_receipts", None)
    if not isinstance(effect_receipts, (list, tuple)) or effect_receipts:
        raise CompositionError("Core language expert returned unexpected effect receipts")

    data = getattr(outcome, "data", None)
    if not isinstance(data, Mapping):
        raise CompositionError("Core language expert result data must be an object")

    verdict = getattr(outcome, "verdict", None)
    status = getattr(verdict, "value", verdict)
    if not isinstance(status, str):
        raise CompositionError("Core language expert result is missing verdict")

    evidence = _validated_evidence_refs(
        getattr(outcome, "evidence_refs", None),
        source="Core language expert",
    )
    explanation = _typed_explanation(
        expert_id,
        operation,
        status,
        data,
        route="Zara Core ZARA-EXPERT/1",
    )

    # Migrated language adapters publish closed operation data plus canonical
    # top-level evidence refs. Do not reinterpret an operation-specific `result`
    # field as transport metadata for those adapters. Older language packages
    # still use the historical nested envelope until their own migration lands.
    if expert_id not in _TYPED_EXPERT_IDS:
        nested = data.get("result")
        if nested is not None:
            if not isinstance(nested, Mapping):
                raise CompositionError("Core language expert nested result must be an object")
            nested_model_calls = nested.get("model_calls")
            if type(nested_model_calls) is not int or nested_model_calls != 0:
                raise CompositionError("Core language expert nested result attempted model use")
            nested_receipts = nested.get("effect_receipts")
            if not isinstance(nested_receipts, (list, tuple)) or nested_receipts:
                raise CompositionError(
                    "Core language expert nested result returned effect receipts"
                )
            raw_evidence = nested.get("evidence", ())
            if isinstance(raw_evidence, (str, bytes)) or not isinstance(
                raw_evidence, (list, tuple)
            ):
                raise CompositionError("Core language expert nested evidence must be a sequence")
            nested_evidence = tuple(str(item) for item in raw_evidence)
            # Core evidence_refs are the authoritative bounded lineage. Only retain
            # nested evidence as a compatibility fallback for older handlers that
            # have not migrated to the canonical top-level envelope yet.
            if nested_evidence and not evidence:
                evidence = nested_evidence
            raw_explanation = nested.get("explanation", ())
            if isinstance(raw_explanation, (str, bytes)) or not isinstance(
                raw_explanation, (list, tuple)
            ):
                raise CompositionError(
                    "Core language expert nested explanation must be a sequence"
                )
            if raw_explanation:
                rendered = " | ".join(str(item) for item in raw_explanation)
                explanation = f"{explanation}: {rendered}"

    return InvocationResult(
        status=status,
        data=dict(data),
        evidence=evidence,
        explanation=explanation,
        model_calls=0,
    )


class LanguageFamilyCompositionInvoker:
    """Bridge language experts into Zara's canonical symbolic composer.

    This direct host bridge owns no registry, scheduler, provider runtime,
    permission state, or usage ledger. Product conversation flows that already
    have a Zara Core activation should prefer
    :class:`CoreLanguageFamilyCompositionInvoker` so expert delegation crosses
    the canonical ZARA-EXPERT/1 lifecycle and generation fences.
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

        payload = _validated_language_payload(expert_id, input_data)
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

        status = outcome.get("verdict")
        if not isinstance(status, str):
            raise CompositionError("language expert result is missing verdict")

        evidence = _validated_evidence_refs(
            outcome.get("evidence_refs"),
            source="language expert",
        )
        explanation = _typed_explanation(
            expert_id,
            operation,
            status,
            data,
            route="the registered language expert host",
        )

        if expert_id not in _TYPED_EXPERT_IDS:
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
                nested_evidence = tuple(str(item) for item in raw_evidence)
                if nested_evidence and not evidence:
                    evidence = nested_evidence
                raw_explanation = nested.get("explanation", ())
                if isinstance(raw_explanation, (str, bytes)) or not isinstance(
                    raw_explanation, (list, tuple)
                ):
                    raise CompositionError("language expert explanation must be a sequence")
                if raw_explanation:
                    explanation = " | ".join(str(item) for item in raw_explanation)

        return InvocationResult(
            status=status,
            data=dict(data),
            evidence=evidence,
            explanation=explanation,
            model_calls=0,
        )


class CoreLanguageFamilyCompositionInvoker:
    """Route language composition through Zara Core's canonical expert registry.

    The caller supplies the existing Core registry plus an activation resolver;
    this adapter creates neither. The resolver must return the already-admitted
    activation for the requested expert/workspace. Core therefore remains the
    owner of activation identity, registry/runtime generation fences,
    cancellation, operation admission, usage accounting, and effect receipts.
    The shared symbolic composer remains the only budget owner.
    """

    def __init__(
        self,
        registry: Any,
        *,
        activation_for: Callable[[str, InvocationFence], Any],
        limits_factory: Callable[..., Any],
    ) -> None:
        if not callable(getattr(registry, "invoke", None)):
            raise TypeError("Core language composition requires a registry with invoke()")
        if not callable(activation_for):
            raise TypeError("activation_for must be callable")
        if not callable(limits_factory):
            raise TypeError("limits_factory must be callable")
        self._registry = registry
        self._activation_for = activation_for
        self._limits_factory = limits_factory

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
        payload = _validated_language_payload(expert_id, input_data)

        try:
            handle = self._activation_for(expert_id, fence)
        except Exception as exc:
            raise CompositionError(
                f"canonical Core activation resolution failed: {exc}"
            ) from exc

        if getattr(handle, "expert_id", None) != expert_id:
            raise CompositionError("canonical Core activation expert identity mismatch")
        if getattr(handle, "workspace", None) != fence.workspace_id:
            raise CompositionError("canonical Core activation workspace mismatch")

        fence.check()
        budget.assert_zero_model_usage()
        try:
            limits = self._limits_factory(max_model_calls=budget.max_model_calls)
            outcome = self._registry.invoke(
                handle,
                operation,
                payload,
                limits=limits,
            )
        except Exception as exc:
            raise CompositionError(
                f"canonical Core expert invocation failed: {exc}"
            ) from exc

        fence.check()
        budget.assert_zero_model_usage()
        return _validated_core_result(expert_id, operation, outcome)


__all__ = [
    "CoreLanguageFamilyCompositionInvoker",
    "LanguageFamilyCompositionInvoker",
]
