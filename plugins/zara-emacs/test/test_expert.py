from __future__ import annotations

import unittest
from dataclasses import replace

from zara.experts import (
    EffectClass,
    ExpertAvailability,
    ExpertDescriptor,
    ExpertLimits,
    ExpertRegistry,
    ExpertStaleGenerationError,
    FallbackPolicy,
    FieldSpec,
    FieldType,
    OperationSpec,
    ReasoningKind,
)
from zara_emacs.expert import (
    EMACS_EXPERT_ID,
    EMACS_EXPERT_SOURCE,
    EmacsExpertAdapter,
    EmacsExpertAdapterError,
    validate_emacs_descriptor,
)


_DIGEST = "sha256:" + "a" * 64


def _operation(operation_id: str, *fields: FieldSpec) -> OperationSpec:
    return OperationSpec(
        operation_id=operation_id,
        input_fields=tuple(fields),
        output_fields=(FieldSpec("result", FieldType.OBJECT),),
    )


def _descriptor(**changes) -> ExpertDescriptor:
    descriptor = ExpertDescriptor(
        protocol="ZARA-EXPERT/1",
        expert_id=EMACS_EXPERT_ID,
        expert_version="1",
        package_namespace="zara-emacs",
        manifest_digest=_DIGEST,
        name="EmacsExpert",
        description="Pure-symbolic dotfiles-owned Emacs documentation expert.",
        source_reference=EMACS_EXPERT_SOURCE,
        reasoning_kind=ReasoningKind.SYMBOLIC,
        operations=(
            _operation(
                "describe",
                FieldSpec("name", FieldType.STRING),
                FieldSpec("kind", FieldType.STRING),
            ),
            _operation("commands", FieldSpec("limit", FieldType.INTEGER)),
            _operation(
                "search",
                FieldSpec("query", FieldType.STRING),
                FieldSpec("limit", FieldType.INTEGER),
            ),
        ),
        applicability_keywords=("emacs",),
        required_capabilities=(),
        possible_effects=(EffectClass.NONE,),
        supported_engines=(),
        supported_platforms=(),
        fallback_policy=FallbackPolicy.FAIL_CLOSED,
        resource_limits=ExpertLimits(max_model_calls=0),
        availability=ExpertAvailability.READY,
    )
    return replace(descriptor, **changes) if changes else descriptor


def _handler(*, expert_operation: str, **payload):
    return {
        "verdict": "succeeded",
        "data": {"operation": expert_operation, "input": payload},
        "evidence_refs": [f"emacs:{expert_operation}:evidence"],
        "usage": {"model_calls": 0},
        "effect_receipts": [],
    }


def _adapter() -> tuple[ExpertRegistry, EmacsExpertAdapter]:
    registry = ExpertRegistry(engines=())
    registry.reload([(_descriptor(), _handler)])
    return registry, EmacsExpertAdapter(registry)


class EmacsExpertAdapterTests(unittest.TestCase):
    def test_adapter_uses_canonical_registry_activation_and_zero_model_budget(self):
        registry, adapter = _adapter()
        handle = adapter.activate(principal="user:test", workspace="workspace:test")

        result = adapter.search(
            handle,
            "describe function",
            request_id="request:emacs-search",
            limit=7,
        )

        self.assertEqual(result.verdict.value, "succeeded")
        self.assertEqual(result.expert_id, EMACS_EXPERT_ID)
        self.assertEqual(result.expert_operation, "search")
        self.assertEqual(
            result.data["input"], {"query": "describe function", "limit": 7}
        )
        self.assertEqual(result.usage["model_calls"], 0)
        self.assertEqual(result.effect_receipts, ())
        self.assertEqual(registry.snapshot().activation_ids, (handle.activation_id,))

    def test_adapter_preserves_exact_generation_fence_after_registry_change(self):
        registry, adapter = _adapter()
        handle = adapter.activate(principal="user:test", workspace="workspace:test")
        other = replace(
            _descriptor(),
            expert_id="zara:expert/other",
            manifest_digest="sha256:" + "b" * 64,
            name="OtherExpert",
            source_reference="test:other",
        )
        registry.reload([(_descriptor(), _handler), (other, _handler)])

        with self.assertRaises(ExpertStaleGenerationError):
            adapter.commands(handle, request_id="request:stale", limit=5)

    def test_adapter_rejects_effect_or_model_authority_widening(self):
        with self.assertRaisesRegex(EmacsExpertAdapterError, "widens effects"):
            validate_emacs_descriptor(
                _descriptor(possible_effects=(EffectClass.MODEL_INFERENCE,))
            )

        with self.assertRaisesRegex(EmacsExpertAdapterError, "max_model_calls=0"):
            validate_emacs_descriptor(
                _descriptor(resource_limits=ExpertLimits(max_model_calls=1))
            )

    def test_adapter_rejects_noncanonical_source_and_missing_operations(self):
        with self.assertRaisesRegex(EmacsExpertAdapterError, "canonical dotfiles"):
            validate_emacs_descriptor(_descriptor(source_reference="plugin:embedded-copy"))

        with self.assertRaisesRegex(EmacsExpertAdapterError, "missing operation"):
            validate_emacs_descriptor(_descriptor(operations=_descriptor().operations[:2]))

    def test_adapter_validates_dotfiles_predicate_bounds_before_dispatch(self):
        _, adapter = _adapter()
        handle = adapter.activate(principal="user:test", workspace="workspace:test")

        with self.assertRaisesRegex(EmacsExpertAdapterError, "limit must be <= 100"):
            adapter.search(handle, "emacs", request_id="request:large", limit=101)
        with self.assertRaisesRegex(EmacsExpertAdapterError, "query length"):
            adapter.search(handle, "x" * 257, request_id="request:query", limit=1)
        with self.assertRaisesRegex(EmacsExpertAdapterError, "requires exactly"):
            adapter.invoke(
                handle,
                "describe",
                {
                    "name": "find-file",
                    "kind": "function",
                    "elisp": "(shell-command \"x\")",
                },
                request_id="request:authority-injection",
            )

    def test_adapter_exposes_read_only_emacs_operations_only(self):
        _, adapter = _adapter()
        handle = adapter.activate(principal="user:test", workspace="workspace:test")

        with self.assertRaisesRegex(
            EmacsExpertAdapterError, "unsupported EmacsExpert operation"
        ):
            adapter.invoke(
                handle,
                "eval",
                {"form": "(shell-command \"id\")"},
                request_id="request:eval",
            )


if __name__ == "__main__":
    unittest.main()
