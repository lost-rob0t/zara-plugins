from __future__ import annotations

from typing import Any, Mapping

from .composition import (
    CompositionError,
    DelegationRequest,
    InvocationFence,
    InvocationResult,
    SharedSymbolicBudget,
)
from .domain import ExpertHost
from .lisp_family import invoke_lisp_operation


_DIALECT_REPAIR_EXPERTS = frozenset(
    {
        "zara:expert/common-lisp",
        "zara:expert/emacs-lisp",
    }
)
_ALLOWED_INPUT_KEYS = frozenset({"arguments"})


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

        unknown = set(input_data) - _ALLOWED_INPUT_KEYS
        if unknown:
            raise CompositionError(
                f"Lisp expert input contains unsupported fields: {sorted(unknown)!r}"
            )
        arguments = input_data.get("arguments", ())
        if isinstance(arguments, (str, bytes)) or not isinstance(arguments, (list, tuple)):
            raise CompositionError("Lisp expert arguments must be a list")
        arguments = list(arguments)

        if expert_id in _DIALECT_REPAIR_EXPERTS and operation == "repair.preview":
            fence.check()
            budget.assert_zero_model_usage()
            return InvocationResult(
                status="succeeded",
                delegations=(
                    DelegationRequest(
                        expert_id="zara:expert/lisp",
                        operation="repair.preview",
                        input={"arguments": arguments},
                        reason="dialect repair delegates to canonical generic Lisp semantics",
                    ),
                ),
                explanation=(
                    f"{expert_id} delegated repair.preview to zara:expert/lisp "
                    "under the caller's shared symbolic budget"
                ),
                model_calls=0,
            )

        raw = invoke_lisp_operation(self._host, expert_id, operation, arguments)
        fence.check()
        budget.assert_zero_model_usage()
        if not isinstance(raw, Mapping):
            raise CompositionError("zara-expert Lisp host returned non-object result")

        trace = raw.get("trace", ())
        if isinstance(trace, (str, bytes)):
            raise CompositionError("zara-expert Lisp host trace must be a sequence")
        evidence = tuple(str(item) for item in trace)
        return InvocationResult(
            status="succeeded" if raw.get("ok", False) else "failed",
            data={"results": raw.get("results", ())},
            evidence=evidence,
            explanation=f"{expert_id} handled {operation} through the registered Lisp expert host",
            model_calls=0,
        )


__all__ = ["LispFamilyCompositionInvoker"]
