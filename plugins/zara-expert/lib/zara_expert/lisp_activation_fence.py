from __future__ import annotations

from typing import Any, Callable

from . import lisp_composition as _base
from .composition import CompositionError, InvocationFence


_MISSING = object()
_ACTIVATION_TEXT_FIELDS = (
    "activation_id",
    "principal",
    "workspace",
    "expert_id",
    "expert_version",
    "manifest_digest",
)
_ACTIVATION_GENERATION_FIELDS = (
    "registry_generation",
    "runtime_generation",
)


def _guard_activation_scalar_identity(handle: Any) -> None:
    """Reject host-language scalar subclasses before Core rereads a handle.

    Zara Core owns activation syntax, lifecycle, leases, and generation freshness.
    This product fence only prevents Python scalar subclasses from widening the
    semantics of fields Core later hashes or compares. Ordinary malformed values
    are deliberately left to the existing Core/canonical validators so their
    established fail-closed contract and error ownership remain unchanged.
    """

    for field in _ACTIVATION_TEXT_FIELDS:
        value = getattr(handle, field, _MISSING)
        if value is _MISSING:
            continue
        if isinstance(value, str) and type(value) is not str:
            raise CompositionError(
                f"canonical Core Lisp activation {field} must not use a string subclass"
            )

    for field in _ACTIVATION_GENERATION_FIELDS:
        value = getattr(handle, field, _MISSING)
        if value is _MISSING:
            continue
        if isinstance(value, int) and type(value) is not int:
            raise CompositionError(
                f"canonical Core Lisp activation {field} must not use an integer subclass"
            )


def _canonical_activation_resolver(
    activation_for: Callable[[str, InvocationFence], Any],
) -> Callable[[str, InvocationFence], Any]:
    """Fence Core activation identity without owning activation state.

    Zara Core remains the registry/activation authority. This wrapper only
    rejects host-language scalar subclasses before the existing Lisp composition
    layer or Core compares activation identity, workspace, lease/generation, or
    bound descriptor values. Subclasses can override equality/hash behavior and
    otherwise make a mismatched handle look current.
    """

    def resolve(expert_id: str, fence: InvocationFence) -> Any:
        handle = activation_for(expert_id, fence)
        _guard_activation_scalar_identity(handle)

        handle_expert_id = getattr(handle, "expert_id", None)
        if type(handle_expert_id) is not str or handle_expert_id != expert_id:
            raise CompositionError("canonical Core Lisp activation expert identity mismatch")

        handle_workspace = getattr(handle, "workspace", None)
        if type(handle_workspace) is not str or handle_workspace != fence.workspace_id:
            raise CompositionError("canonical Core Lisp activation workspace mismatch")

        return handle

    return resolve


def install_lisp_activation_handle_type_fence() -> None:
    """Install one narrow type fence on the existing Core Lisp invoker.

    This does not add an activation store, registry, scheduler, capability path,
    or parser. It composes with the existing Core resolver and preserves the
    caller-owned zero-model budget and generation/cancellation fence.
    """

    if getattr(_base, "_LISP_ACTIVATION_HANDLE_TYPE_FENCE_INSTALLED", False):
        return

    original_init = _base.CoreLispFamilyCompositionInvoker.__init__

    def fenced_init(
        self: Any,
        registry: Any,
        *,
        activation_for: Callable[[str, InvocationFence], Any],
        limits_factory: Callable[..., Any],
    ) -> None:
        if not callable(activation_for):
            raise TypeError("activation_for must be callable")
        original_init(
            self,
            registry,
            activation_for=_canonical_activation_resolver(activation_for),
            limits_factory=limits_factory,
        )

    _base.CoreLispFamilyCompositionInvoker.__init__ = fenced_init
    _base._LISP_ACTIVATION_HANDLE_TYPE_FENCE_INSTALLED = True


__all__ = ["install_lisp_activation_handle_type_fence"]
