from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import lisp_output_contract as _output
from .composition import CompositionError


def _guard_nested_container_identity(value: Any) -> None:
    """Reject non-canonical mutable containers before symbolic projection.

    The Lisp output contract recursively snapshots built-in dict/list/tuple
    containers after the existing semantic validators succeed. A subclass or
    arbitrary Mapping would otherwise survive that snapshot by identity and stay
    mutable from the host side. This guard owns only Python wire/container
    identity; Prolog-RLM remains the parser/reader/repair semantic authority.
    """

    if isinstance(value, Mapping):
        if type(value) is not dict:
            raise CompositionError(
                "Lisp symbolic result mapping must be a built-in dict"
            )
        return
    if isinstance(value, list) and type(value) is not list:
        raise CompositionError("Lisp symbolic result list must be a built-in list")
    if isinstance(value, tuple) and type(value) is not tuple:
        raise CompositionError("Lisp symbolic result tuple must be a built-in tuple")


def install_lisp_nested_result_container_fence() -> None:
    """Layer canonical nested-container identity onto the existing snapshot."""

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
