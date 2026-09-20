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
        arguments = input_data.get("arguments", ())
        if isinstance(arguments, (str, bytes)) or not isinstance(arguments, (list, tuple)):
            raise CompositionError("Lisp expert arguments must be a list")
        arguments = list(arguments)

        if expert_id in _DIALECT_REPAIR_EXPERTS and operation == "repair.preview":
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

        raw = invoke_lisp_operation(self._host, expert_id, operation, arguments)
        fence.check()
        budget.assert_zero_model_usage()
        if not isinstance(raw, Mapping):
            raise CompositionError("zara-expert Lisp host returned non-object result")

        trace = raw.get("trace", ())
        if isinstance(trace, (str, bytes)):
            raise CompositionError("zara-expert Lisp host trace must be a sequence")
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
            data={"results": raw.get("results", ())},
            evidence=evidence,
            explanation=f"{expert_id} handled {operation} through the registered Lisp expert host",
            model_calls=0,
        )


__all__ = ["LispFamilyCompositionInvoker"]
