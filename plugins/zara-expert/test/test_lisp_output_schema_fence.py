import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert import CoreLispFamilyCompositionInvoker
from zara_expert.composition import CompositionError, InvocationFence, MetaExpertComposer, SharedSymbolicBudget


CANONICAL_EVIDENCE_REF = f"evidence:lisp:sha256:{'0' * 64}"


class RecordingCoreRegistry:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def invoke(self, handle, operation, payload, *, limits):
        self.calls.append((handle, operation, dict(payload), limits))
        return self.result


class CoreLimits:
    def __init__(self, *, max_model_calls):
        self.max_model_calls = max_model_calls


def current_fence():
    return InvocationFence(
        workspace_id="project",
        workspace_generation=7,
        is_cancelled=lambda: False,
        is_current_generation=lambda workspace, generation: (
            workspace == "project" and generation == 7
        ),
    )


def core_result(data, *, status="succeeded", evidence_refs=(CANONICAL_EVIDENCE_REF,)):
    return SimpleNamespace(
        verdict=SimpleNamespace(value=status),
        data=data,
        evidence_refs=evidence_refs,
        usage={"model_calls": 0},
        effect_receipts=(),
    )


def canonical_result_data():
    return {
        "result": {
            "ok": True,
            "results": ["balanced(true)"],
            "trace": ["lisp:structural_check/2"],
        }
    }


class LispOutputSchemaFenceTests(unittest.TestCase):
    def invoke(self, data, *, status="succeeded", evidence_refs=(CANONICAL_EVIDENCE_REF,)):
        handle = SimpleNamespace(expert_id="zara:expert/lisp", workspace="project")
        registry = RecordingCoreRegistry(
            core_result(data, status=status, evidence_refs=evidence_refs)
        )
        invoker = CoreLispFamilyCompositionInvoker(
            registry,
            activation_for=lambda _expert_id, _fence: handle,
            limits_factory=CoreLimits,
        )
        budget = SharedSymbolicBudget(max_invocations=1, max_model_calls=0)
        node = MetaExpertComposer(invoker).invoke(
            "zara:expert/lisp",
            "structural.check",
            {"arguments": ["(ok)"]},
            budget=budget,
            fence=current_fence(),
        )
        return node, registry, budget

    def test_core_lisp_rejects_undeclared_or_malformed_output_fields(self):
        malformed = (
            {
                **canonical_result_data(),
                "renderer_fallback": "provider",
            },
            {
                **canonical_result_data(),
                "evidence_refs": "provider://fallback",
            },
            {
                **canonical_result_data(),
                "evidence_refs": ["provider:openai"],
            },
        )

        for data in malformed:
            with self.subTest(data=data):
                with self.assertRaisesRegex(CompositionError, "invalid-expert-output"):
                    self.invoke(data)

    def test_core_lisp_rejects_noncanonical_top_level_evidence_refs(self):
        noncanonical = (
            ("provider:openai",),
            ("registered-predicate",),
            ("evidence:lisp:test",),
            ("zara.verified-outcome/v1:outcome:postcondition/not-allowed-here",),
        )

        for evidence_refs in noncanonical:
            with self.subTest(evidence_refs=evidence_refs):
                with self.assertRaisesRegex(CompositionError, "invalid-expert-output"):
                    self.invoke(canonical_result_data(), evidence_refs=evidence_refs)

    def test_core_lisp_accepts_declared_read_only_output_shape_at_zero_models(self):
        node, registry, budget = self.invoke(canonical_result_data())

        self.assertEqual(node.status, "succeeded")
        self.assertEqual(node.data, canonical_result_data())
        self.assertEqual(node.evidence, (CANONICAL_EVIDENCE_REF,))
        self.assertEqual(len(registry.calls), 1)
        self.assertEqual(registry.calls[0][3].max_model_calls, 0)
        self.assertEqual(budget.model_calls_used, 0)

    def test_core_lisp_accepts_empty_canonical_cancelled_output_without_widening_schema(self):
        # Cancellation is a fence: Core must be able to discard late predicate
        # output entirely without the adapter demanding that stale output back.
        node, registry, budget = self.invoke(
            {},
            status="cancelled",
            evidence_refs=(),
        )

        self.assertEqual(node.status, "cancelled")
        self.assertEqual(node.data, {})
        self.assertEqual(node.evidence, ())
        self.assertEqual(len(registry.calls), 1)
        self.assertEqual(registry.calls[0][3].max_model_calls, 0)
        self.assertEqual(budget.model_calls_used, 0)

    def test_core_lisp_rejects_cancelled_results_with_late_output(self):
        # The cancelled projection is terminal regardless of whether late output
        # still fits an otherwise valid Lisp operation schema.
        leak_cases = (
            (canonical_result_data(), ()),
            ({}, ("evidence:lisp:late",)),
            ({"renderer_fallback": "provider"}, ()),
        )
        for data, evidence_refs in leak_cases:
            with self.subTest(data=data, evidence_refs=evidence_refs):
                with self.assertRaisesRegex(
                    CompositionError,
                    "cancelled-expert-output-leak",
                ):
                    self.invoke(
                        data,
                        status="cancelled",
                        evidence_refs=evidence_refs,
                    )

    def test_core_lisp_rejects_malformed_top_level_evidence_before_projection(self):
        with self.assertRaisesRegex(
            CompositionError,
            "evidence_refs must be a sequence",
        ):
            self.invoke(
                {},
                status="cancelled",
                evidence_refs="evidence:lisp:late",
            )


if __name__ == "__main__":
    unittest.main()
