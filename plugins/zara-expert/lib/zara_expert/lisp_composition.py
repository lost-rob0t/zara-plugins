from __future__ import annotations

from typing import Any, Mapping

from .composition import (
    CompositionError,
    DelegationRequest,
    InvocationFence,
    InvocationResult,
    SharedSymbolicBudget,
)
from .domain import ExpertError, ExpertHost
from .lisp_family import (
    _core_operation_arguments,
    invoke_lisp_operation,
    make_lisp_expert_handler,
)


_DIALECT_REPAIR_EXPERTS = frozenset(
    {
        "zara:expert/common-lisp",
        "zara:expert/emacs-lisp",
    }
)
_ALLOWED_INPUT_KEYS = frozenset({"arguments"})


def _handler_outcome_to_invocation_result(
    expert_id: str,
    operation: str,
    outcome: Any,
) -> InvocationResult:
    if not isinstance(outcome, Mapping):
        raise CompositionError("Lisp expert handler returned non-object result")

    usage = outcome.get("usage")
    if not isinstance(usage, Mapping):
        raise CompositionError("Lisp expert result is missing usage ledger")
    model_calls = usage.get("model_calls")
    if type(model_calls) is not int or model_calls != 0:
        raise CompositionError("Lisp expert attempted model use")

    effect_receipts = outcome.get("effect_receipts")
    if not isinstance(effect_receipts, (list, tuple)) or effect_receipts:
        raise CompositionError("Lisp expert returned unexpected effect receipts")

    data = outcome.get("data")
    if not isinstance(data, Mapping):
        raise CompositionError("Lisp expert result data must be an object")
    nested = data.get("result")
    if not isinstance(nested, Mapping):
        raise CompositionError("Lisp expert nested result must be an object")

    nested_model_calls = nested.get("model_calls")
    if nested_model_calls is not None and (
        type(nested_model_calls) is not int or nested_model_calls != 0
    ):
        raise CompositionError("Lisp expert nested result attempted model use")
    nested_receipts = nested.get("effect_receipts")
    if nested_receipts is not None and (
        not isinstance(nested_receipts, (list, tuple)) or nested_receipts
    ):
        raise CompositionError("Lisp expert nested result returned effect receipts")

    evidence_refs = outcome.get("evidence_refs", ())
    if isinstance(evidence_refs, (str, bytes)) or not isinstance(
        evidence_refs, (list, tuple)
    ):
        raise CompositionError("Lisp expert evidence_refs must be a sequence")
    evidence = tuple(str(item) for item in evidence_refs)
    if not evidence:
        trace = nested.get("trace", ())
        if isinstance(trace, (str, bytes)) or not isinstance(trace, (list, tuple)):
            raise CompositionError("Lisp expert host trace must be a sequence")
        evidence = tuple(str(item) for item in trace)

    status = outcome.get("verdict")
    if not isinstance(status, str):
        raise CompositionError("Lisp expert result is missing verdict")

    return InvocationResult(
        status=status,
        data=dict(data),
        evidence=evidence,
        explanation=(
            f"{expert_id} handled {operation} through the registered Lisp expert host"
        ),
        model_calls=0,
    )


class LispFamilyCompositionInvoker:
    """Bridge Lisp-family adapters into Zara's canonical symbolic composer.

    The bridge owns no registry, scheduler, provider runtime, or permission state.
    It only translates the already-declared Lisp-family delegation contract into
    a canonical child invocation while preserving the caller-owned budget and
    generation/cancellation fence.
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

        # repair.apply has a different public schema from predicate-backed
        # operations. Preserve that canonical schema and fail at the existing
        # Zara typed-effect boundary before any expert backend can run.
        if operation == "repair.apply":
            invoke_lisp_operation(self._host, expert_id, operation, ())
            raise AssertionError("repair.apply must fail closed before backend dispatch")

        unknown = set(input_data) - _ALLOWED_INPUT_KEYS
        if unknown:
            raise CompositionError(
                f"Lisp expert input contains unsupported fields: {sorted(unknown)!r}"
            )
        arguments = input_data.get("arguments", [])
        if not isinstance(arguments, list):
            raise CompositionError("Lisp expert arguments must be a list")
        arguments = list(arguments)

        if expert_id in _DIALECT_REPAIR_EXPERTS and operation == "repair.preview":
            try:
                # Validate the public payload with the exact same ABI helper used
                # by the Core-facing handler. The returned private Result variable
                # is intentionally discarded here; the delegated Lisp child owns
                # and injects its own result variable at dispatch time.
                _core_operation_arguments(operation, arguments)
            except ExpertError as exc:
                raise CompositionError(str(exc)) from exc
            fence.check()
            budget.assert_zero_model_usage()
            return InvocationResult(
                # The dialect adapter only proved that delegation is required.
                # It must not claim an overall successful repair before the
                # canonical Lisp child has produced successful evidence. The
                # generic composer currently preserves parent/child statuses
                # independently, so fail closed here instead of false-greening
                # a failed/unknown child as a successful dialect repair.
                status="unknown",
                data={
                    "delegated_to": "zara:expert/lisp",
                    "delegation_required": True,
                },
                delegations=(
                    DelegationRequest(
                        expert_id="zara:expert/lisp",
                        operation="repair.preview",
                        input={"arguments": arguments},
                        reason="dialect repair delegates to canonical generic Lisp semantics",
                    ),
                ),
                explanation=(
                    f"{expert_id} requires zara:expert/lisp repair.preview evidence; "
                    "the dialect adapter does not claim success before the child result"
                ),
                model_calls=0,
            )

        handler = make_lisp_expert_handler(self._host, expert_id)
        try:
            outcome = handler(
                expert_operation=operation,
                arguments=arguments,
            )
        except ExpertError as exc:
            raise CompositionError(str(exc)) from exc
        fence.check()
        budget.assert_zero_model_usage()
        return _handler_outcome_to_invocation_result(expert_id, operation, outcome)


__all__ = ["LispFamilyCompositionInvoker"]
