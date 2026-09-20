"""Canonical ZARA-EXPERT/1 consumer for the dotfiles-owned EmacsExpert.

This module deliberately owns no registry, activation state, Prolog runtime, or
expert source.  It is a narrow zara-emacs adapter over :mod:`zara.experts`, so
lifecycle, generation fencing, cancellation, budgets, and authority remain
owned by Zara Core.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from zara.experts import (
    ActivationHandle,
    EffectClass,
    ExpertDescriptor,
    ExpertLimits,
    ExpertRegistry,
    ExpertResult,
    FallbackPolicy,
    ReasoningKind,
    ZARA_EXPERT_PROTOCOL,
)


EMACS_EXPERT_ID = "zara:expert/emacs"
EMACS_EXPERT_SOURCE = "dotfiles:.zara/experts/emacs"
EMACS_EXPERT_OPERATIONS = frozenset({"describe", "commands", "search"})
_MAX_MODEL_CALLS = 0
_ALLOWED_EFFECTS = frozenset({EffectClass.NONE, EffectClass.FILESYSTEM_READ})


class EmacsExpertAdapterError(RuntimeError):
    """Fail-closed adapter error for canonical EmacsExpert consumption."""


def _require_int(value: object, *, field: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise EmacsExpertAdapterError(f"{field} must be an integer >= {minimum}")
    return value


def _bounded_text(value: object, *, field: str, minimum: int = 1, maximum: int) -> str:
    if not isinstance(value, str):
        raise EmacsExpertAdapterError(f"{field} must be text")
    if not minimum <= len(value) <= maximum:
        raise EmacsExpertAdapterError(
            f"{field} length must be between {minimum} and {maximum}"
        )
    if value != value.strip():
        raise EmacsExpertAdapterError(f"{field} must not contain surrounding whitespace")
    return value


def _validate_input(operation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise EmacsExpertAdapterError("expert input must be an object")
    data = dict(payload)
    if operation == "describe":
        if set(data) != {"name", "kind"}:
            raise EmacsExpertAdapterError("describe requires exactly name and kind")
        data["name"] = _bounded_text(data["name"], field="name", maximum=256)
        data["kind"] = _bounded_text(data["kind"], field="kind", maximum=64)
        return data
    if operation == "commands":
        if set(data) != {"limit"}:
            raise EmacsExpertAdapterError("commands requires exactly limit")
        data["limit"] = _require_int(data["limit"], field="limit", minimum=1)
        if data["limit"] > 100:
            raise EmacsExpertAdapterError("limit must be <= 100")
        return data
    if operation == "search":
        if set(data) != {"query", "limit"}:
            raise EmacsExpertAdapterError("search requires exactly query and limit")
        data["query"] = _bounded_text(data["query"], field="query", maximum=256)
        data["limit"] = _require_int(data["limit"], field="limit", minimum=1)
        if data["limit"] > 100:
            raise EmacsExpertAdapterError("limit must be <= 100")
        return data
    raise EmacsExpertAdapterError(f"unsupported EmacsExpert operation: {operation!r}")


def validate_emacs_descriptor(descriptor: ExpertDescriptor) -> ExpertDescriptor:
    """Validate the canonical descriptor without granting any new authority."""

    if not isinstance(descriptor, ExpertDescriptor):
        raise EmacsExpertAdapterError("EmacsExpert descriptor must be ExpertDescriptor")
    if descriptor.protocol != ZARA_EXPERT_PROTOCOL:
        raise EmacsExpertAdapterError("EmacsExpert protocol is not ZARA-EXPERT/1")
    if descriptor.expert_id != EMACS_EXPERT_ID:
        raise EmacsExpertAdapterError("unexpected EmacsExpert identity")
    if descriptor.source_reference != EMACS_EXPERT_SOURCE:
        raise EmacsExpertAdapterError("EmacsExpert source is not the canonical dotfiles package")
    if descriptor.reasoning_kind is not ReasoningKind.SYMBOLIC:
        raise EmacsExpertAdapterError("EmacsExpert must remain pure symbolic")
    if descriptor.fallback_policy is not FallbackPolicy.FAIL_CLOSED:
        raise EmacsExpertAdapterError("EmacsExpert must fail closed")
    if descriptor.resource_limits is None:
        raise EmacsExpertAdapterError("EmacsExpert must declare resource limits")
    if type(descriptor.resource_limits.max_model_calls) is not int:
        raise EmacsExpertAdapterError("EmacsExpert max_model_calls must be an integer")
    if descriptor.resource_limits.max_model_calls != _MAX_MODEL_CALLS:
        raise EmacsExpertAdapterError("EmacsExpert requires max_model_calls=0")
    forbidden = set(descriptor.possible_effects) - _ALLOWED_EFFECTS
    if forbidden:
        names = ", ".join(sorted(item.value for item in forbidden))
        raise EmacsExpertAdapterError(f"EmacsExpert descriptor widens effects: {names}")
    operations = {item.operation_id for item in descriptor.operations}
    missing = sorted(EMACS_EXPERT_OPERATIONS - operations)
    if missing:
        raise EmacsExpertAdapterError(
            f"EmacsExpert descriptor is missing operation: {missing[0]}"
        )
    return descriptor


class EmacsExpertAdapter:
    """Thin consumer of Zara Core's one canonical expert registry.

    Activation handles are Core-owned.  Every invocation reuses the handle's
    exact registry/runtime generations and narrows the model budget to zero.
    The adapter rejects result identity/generation drift, non-zero model usage,
    and effect receipts because the Emacs documentation expert is read-only.
    """

    def __init__(self, registry: ExpertRegistry) -> None:
        if not isinstance(registry, ExpertRegistry):
            raise EmacsExpertAdapterError("registry must be Zara's canonical ExpertRegistry")
        self._registry = registry

    def descriptor(self) -> ExpertDescriptor:
        return validate_emacs_descriptor(
            ExpertDescriptor.from_wire(self._registry.describe(EMACS_EXPERT_ID))
        )

    def activate(
        self,
        *,
        principal: str,
        workspace: str,
    ) -> ActivationHandle:
        descriptor = self.descriptor()
        handle, receipt = self._registry.activate(
            principal,
            workspace,
            EMACS_EXPERT_ID,
            expected_registry_generation=self._registry.generation,
            expected_runtime_generation=self._registry.runtime_generation,
        )
        if handle.expert_id != descriptor.expert_id:
            raise EmacsExpertAdapterError("activation returned the wrong expert identity")
        if handle.expert_version != descriptor.expert_version:
            raise EmacsExpertAdapterError("activation changed EmacsExpert version")
        if handle.manifest_digest != descriptor.manifest_digest:
            raise EmacsExpertAdapterError("activation changed EmacsExpert digest")
        if receipt.get("state") != "active":
            raise EmacsExpertAdapterError("EmacsExpert activation did not become active")
        return handle

    def invoke(
        self,
        handle: ActivationHandle,
        operation: str,
        payload: Mapping[str, Any],
        *,
        request_id: str,
        timeout_ms: int = 30_000,
        max_results: int = 100,
        max_output_bytes: int = 1_048_576,
    ) -> ExpertResult:
        self._validate_handle(handle)
        request_id = _bounded_text(request_id, field="request_id", maximum=128)
        data = _validate_input(operation, payload)
        limits = ExpertLimits(
            timeout_ms=_require_int(timeout_ms, field="timeout_ms", minimum=1),
            max_results=_require_int(max_results, field="max_results", minimum=1),
            max_output_bytes=_require_int(
                max_output_bytes, field="max_output_bytes", minimum=1
            ),
            max_model_calls=_MAX_MODEL_CALLS,
        )
        result = self._registry.invoke(
            handle,
            operation,
            data,
            limits=limits,
            request_id=request_id,
        )
        return self._validate_result(handle, operation, request_id, result)

    def search(
        self,
        handle: ActivationHandle,
        query: str,
        *,
        request_id: str,
        limit: int = 20,
    ) -> ExpertResult:
        return self.invoke(
            handle,
            "search",
            {"query": query, "limit": limit},
            request_id=request_id,
            max_results=limit,
        )

    def commands(
        self,
        handle: ActivationHandle,
        *,
        request_id: str,
        limit: int = 20,
    ) -> ExpertResult:
        return self.invoke(
            handle,
            "commands",
            {"limit": limit},
            request_id=request_id,
            max_results=limit,
        )

    def describe(
        self,
        handle: ActivationHandle,
        name: str,
        kind: str,
        *,
        request_id: str,
    ) -> ExpertResult:
        return self.invoke(
            handle,
            "describe",
            {"name": name, "kind": kind},
            request_id=request_id,
        )

    @staticmethod
    def _validate_handle(handle: ActivationHandle) -> None:
        if not isinstance(handle, ActivationHandle):
            raise EmacsExpertAdapterError("invoke requires a canonical ActivationHandle")
        if handle.expert_id != EMACS_EXPERT_ID:
            raise EmacsExpertAdapterError("activation handle belongs to another expert")

    @staticmethod
    def _validate_result(
        handle: ActivationHandle,
        operation: str,
        request_id: str,
        result: ExpertResult,
    ) -> ExpertResult:
        if not isinstance(result, ExpertResult):
            raise EmacsExpertAdapterError("canonical expert invocation returned invalid result")
        expected = {
            "protocol": ZARA_EXPERT_PROTOCOL,
            "request_id": request_id,
            "activation_id": handle.activation_id,
            "expert_id": handle.expert_id,
            "expert_version": handle.expert_version,
            "manifest_digest": handle.manifest_digest,
            "expert_operation": operation,
            "resolved_registry_generation": handle.registry_generation,
            "resolved_runtime_generation": handle.runtime_generation,
        }
        for field, wanted in expected.items():
            if getattr(result, field) != wanted:
                raise EmacsExpertAdapterError(
                    f"EmacsExpert result changed canonical {field}"
                )
        model_calls = result.usage.get("model_calls")
        if type(model_calls) is not int or model_calls != _MAX_MODEL_CALLS:
            raise EmacsExpertAdapterError("EmacsExpert result model-call ledger is not zero")
        if result.effect_receipts:
            raise EmacsExpertAdapterError(
                "read-only EmacsExpert returned unexpected effect receipts"
            )
        return result


__all__ = [
    "EMACS_EXPERT_ID",
    "EMACS_EXPERT_OPERATIONS",
    "EMACS_EXPERT_SOURCE",
    "EmacsExpertAdapter",
    "EmacsExpertAdapterError",
    "validate_emacs_descriptor",
]
