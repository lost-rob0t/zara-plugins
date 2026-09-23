from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from . import lisp_output_contract as _output
from .composition import CompositionError


def _guard_nested_container_identity(value: Any) -> None:
    """Reject non-canonical host identities before symbolic projection.

    The Lisp output contract recursively snapshots built-in dict/list/tuple
    containers after the existing semantic validators succeed. A subclass or
    arbitrary Mapping would otherwise survive that snapshot by identity and stay
    mutable from the host side. Mapping keys are also preserved by identity, so
    they must be exact built-in strings rather than host-controlled subclasses.
    Scalar subclasses accepted by the shared inert JSON-like validator can
    likewise carry host-controlled equality/hash behavior into durable/public
    projection. Exact built-in floats must additionally be finite so durable
    Desktop/Android JSON semantics cannot diverge on NaN or infinities. This
    guard owns only Python wire/container/scalar identity; Prolog-RLM remains the
    parser/reader/repair semantic authority.
    """

    if isinstance(value, Mapping):
        if type(value) is not dict:
            raise CompositionError(
                "Lisp symbolic result mapping must be a built-in dict"
            )
        if any(type(key) is not str for key in value):
            raise CompositionError(
                "Lisp symbolic result mapping keys must be exact built-in strings"
            )
        return
    if isinstance(value, list) and type(value) is not list:
        raise CompositionError("Lisp symbolic result list must be a built-in list")
    if isinstance(value, tuple) and type(value) is not tuple:
        raise CompositionError("Lisp symbolic result tuple must be a built-in tuple")
    if isinstance(value, str) and type(value) is not str:
        raise CompositionError("Lisp symbolic result string must be a built-in string")
    if isinstance(value, (int, float)) and type(value) not in (int, float, bool):
        raise CompositionError(
            "Lisp symbolic result scalar must use an exact built-in wire type"
        )
    if type(value) is float and not math.isfinite(value):
        raise CompositionError(
            "Lisp symbolic result numbers must be finite JSON values"
        )


def install_lisp_nested_result_container_fence() -> None:
    """Layer canonical nested host identity onto the existing snapshot."""

    if getattr(_output, "_LISP_NESTED_RESULT_CONTAINER_FENCE_INSTALLED", False):
        return

    original_snapshot = _output._snapshot_symbolic_value

    def fenced_snapshot(value: Any) -> Any:
        _guard_nested_container_identity(value)
        # The original helper recurses through the module-global symbol. Once
        # installed, every nested value therefore re-enters this same guard.
        return original_snapshot(value)

    _output._snapshot_symbolic_value = fenced_snapshot
    _output._LISP_NESTED_RESULT_CONTAINER_FENCE_INSTALLED = True


__all__ = ["install_lisp_nested_result_container_fence"]
