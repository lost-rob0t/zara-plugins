import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.composition import (
    CompositionError,
    InvocationFence,
    SharedSymbolicBudget,
)
from zara_expert.language_composition import (
    CoreLanguageFamilyCompositionInvoker,
    LanguageFamilyCompositionInvoker,
)


EXPERT_IDS = (
    "zara:expert/prolog",
    "zara:expert/python",
    "zara:expert/nim",
    "zara:expert/javascript",
    "zara:expert/typescript",
    "zara:expert/java",
    "zara:expert/kotlin",
)

PRIMARY_EXPERT_IDS = (
    "zara:expert/prolog",
    "zara:expert/python",
    "zara:expert/nim",
)

FOUR_LANGUAGE_EXPERT_IDS = (
    "zara:expert/javascript",
    "zara:expert/typescript",
    "zara:expert/java",
    "zara:expert/kotlin",
)


class CoreLimits:
    def __init__(self, *, max_model_calls):
        self.max_model_calls = max_model_calls


class StaticRegistry:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def invoke(self, handle, operation, payload, *, limits):
        self.calls.append((handle, operation, dict(payload), limits))
        return self.result


class _ForgedText:
    """Object that must never acquire trust by stringification after replay."""

    def __init__(self, rendered):
        self.rendered = rendered

    def __str__(self):
        return self.rendered


class TypedLanguageCompositionContractTests(unittest.TestCase):
    @staticmethod
    def _fence():
        return InvocationFence(
            workspace_id="workspace-typed",
            workspace_generation=17,
            is_cancelled=lambda: False,
            is_current_generation=lambda _workspace, _generation: True,
        )

    def test_direct_composition_uses_top_level_evidence_refs_for_typed_outputs(self):
        invoker = LanguageFamilyCompositionInvoker(object())

        for index, expert_id in enumerate(EXPERT_IDS, start=1):
            with self.subTest(expert_id=expert_id):
                evidence_ref = f"evidence:typed:{index}"
                fake_handler = lambda **_kwargs: {
                    "verdict": "succeeded",
                    "data": {"diagnostics": [f"diagnostic:{index}"]},
                    "evidence_refs": [evidence_ref],
                    "usage": {"model_calls": 0},
                    "effect_receipts": [],
                }
                with patch(
                    "zara_expert.language_composition.make_language_expert_handler",
                    return_value=fake_handler,
                ):
                    result = invoker(
                        expert_id,
                        "diagnose",
                        {
                            "source": f"symbolic source {index}",
                            "source_generation": f"generation:{index}",
                        },
                        budget=SharedSymbolicBudget(max_model_calls=0),
                        fence=self._fence(),
                        parent_path=(),
                    )

                self.assertEqual(result.status, "succeeded")
                self.assertEqual(result.data, {"diagnostics": [f"diagnostic:{index}"]})
                self.assertNotIn("result", result.data)
                self.assertEqual(result.evidence, (evidence_ref,))
                self.assertEqual(result.model_calls, 0)

    def test_four_language_inspect_result_is_operation_data_not_legacy_transport(self):
        invoker = LanguageFamilyCompositionInvoker(object())

        for index, expert_id in enumerate(FOUR_LANGUAGE_EXPERT_IDS, start=1):
            with self.subTest(expert_id=expert_id):
                evidence_ref = f"evidence:inspect:{index}"
                operation_result = {
                    "language": expert_id.rsplit("/", 1)[-1],
                    "symbols": [f"symbol:{index}"],
                }
                fake_handler = lambda **_kwargs: {
                    "verdict": "succeeded",
                    "data": {"result": operation_result},
                    "evidence_refs": [evidence_ref],
                    "usage": {"model_calls": 0},
                    "effect_receipts": [],
                }
                with patch(
                    "zara_expert.language_composition.make_language_expert_handler",
                    return_value=fake_handler,
                ):
                    result = invoker(
                        expert_id,
                        "inspect",
                        {
                            "source": f"symbolic source {index}",
                            "source_generation": f"generation:{index}",
                        },
                        budget=SharedSymbolicBudget(max_model_calls=0),
                        fence=self._fence(),
                        parent_path=(),
                    )

                self.assertEqual(result.status, "succeeded")
                self.assertEqual(result.data, {"result": operation_result})
                self.assertEqual(result.evidence, (evidence_ref,))
                self.assertEqual(result.model_calls, 0)

    def test_core_composition_renders_typed_explain_trace_without_legacy_result(self):
        for index, expert_id in enumerate(EXPERT_IDS, start=1):
            with self.subTest(expert_id=expert_id):
                trace = f"rule:typed-explain:{index}"
                result = SimpleNamespace(
                    verdict=SimpleNamespace(value="succeeded"),
                    data={
                        "explanation": {
                            "symbolic_terms": [f"decision(symbolic_{index})."],
                            "trace": [trace],
                        }
                    },
                    evidence_refs=(f"evidence:core:{index}",),
                    usage={"model_calls": 0},
                    effect_receipts=(),
                )
                registry = StaticRegistry(result)
                handle = SimpleNamespace(expert_id=expert_id, workspace="workspace-typed")
                invoker = CoreLanguageFamilyCompositionInvoker(
                    registry,
                    activation_for=lambda _expert_id, _fence, handle=handle: handle,
                    limits_factory=CoreLimits,
                )

                outcome = invoker(
                    expert_id,
                    "explain",
                    {
                        "decision_ref": f"decision:{index}",
                        "source_generation": f"generation:{index}",
                    },
                    budget=SharedSymbolicBudget(max_model_calls=0),
                    fence=self._fence(),
                    parent_path=(),
                )

                self.assertEqual(outcome.status, "succeeded")
                self.assertEqual(outcome.evidence, (f"evidence:core:{index}",))
                self.assertIn(trace, outcome.explanation)
                self.assertNotIn("result", outcome.data)
                self.assertEqual(outcome.model_calls, 0)
                self.assertEqual(registry.calls[0][3].max_model_calls, 0)

    def test_primary_direct_composition_rejects_replayed_non_string_evidence_refs(self):
        invoker = LanguageFamilyCompositionInvoker(object())

        for expert_id in PRIMARY_EXPERT_IDS:
            with self.subTest(expert_id=expert_id):
                fake_handler = lambda **_kwargs: {
                    "verdict": "succeeded",
                    "data": {"diagnostics": ["diagnostic(symbolic)."]},
                    "evidence_refs": [_ForgedText("evidence:language:sha256:forged")],
                    "usage": {"model_calls": 0},
                    "effect_receipts": [],
                }
                with patch(
                    "zara_expert.language_composition.make_language_expert_handler",
                    return_value=fake_handler,
                ):
                    with self.assertRaisesRegex(
                        CompositionError,
                        "evidence_refs must contain exact strings",
                    ):
                        invoker(
                            expert_id,
                            "diagnose",
                            {
                                "source": "symbolic source",
                                "source_generation": "generation:replay",
                            },
                            budget=SharedSymbolicBudget(max_model_calls=0),
                            fence=self._fence(),
                            parent_path=(),
                        )

    def test_primary_core_composition_rejects_replayed_non_string_evidence_refs(self):
        for expert_id in PRIMARY_EXPERT_IDS:
            with self.subTest(expert_id=expert_id):
                result = SimpleNamespace(
                    verdict=SimpleNamespace(value="succeeded"),
                    data={"diagnostics": ["diagnostic(symbolic)."]},
                    evidence_refs=(_ForgedText("evidence:language:sha256:forged"),),
                    usage={"model_calls": 0},
                    effect_receipts=(),
                )
                registry = StaticRegistry(result)
                handle = SimpleNamespace(expert_id=expert_id, workspace="workspace-typed")
                invoker = CoreLanguageFamilyCompositionInvoker(
                    registry,
                    activation_for=lambda _expert_id, _fence, handle=handle: handle,
                    limits_factory=CoreLimits,
                )

                with self.assertRaisesRegex(
                    CompositionError,
                    "evidence_refs must contain exact strings",
                ):
                    invoker(
                        expert_id,
                        "diagnose",
                        {
                            "source": "symbolic source",
                            "source_generation": "generation:replay",
                        },
                        budget=SharedSymbolicBudget(max_model_calls=0),
                        fence=self._fence(),
                        parent_path=(),
                    )

    def test_primary_core_composition_rejects_replayed_non_string_explanation_items(self):
        malformed_cases = (
            {
                "symbolic_terms": ["decision(symbolic)."],
                "trace": [_ForgedText("rule:forged")],
            },
            {
                "symbolic_terms": [_ForgedText("decision(forged).")],
                "trace": [],
            },
        )
        for expert_id in PRIMARY_EXPERT_IDS:
            for explanation in malformed_cases:
                with self.subTest(expert_id=expert_id, explanation=explanation):
                    result = SimpleNamespace(
                        verdict=SimpleNamespace(value="succeeded"),
                        data={"explanation": explanation},
                        evidence_refs=("evidence:language:sha256:trusted",),
                        usage={"model_calls": 0},
                        effect_receipts=(),
                    )
                    registry = StaticRegistry(result)
                    handle = SimpleNamespace(expert_id=expert_id, workspace="workspace-typed")
                    invoker = CoreLanguageFamilyCompositionInvoker(
                        registry,
                        activation_for=lambda _expert_id, _fence, handle=handle: handle,
                        limits_factory=CoreLimits,
                    )

                    with self.assertRaisesRegex(
                        CompositionError,
                        "typed language explanation .* exact strings",
                    ):
                        invoker(
                            expert_id,
                            "explain",
                            {
                                "decision_ref": "decision:replay",
                                "source_generation": "generation:replay",
                            },
                            budget=SharedSymbolicBudget(max_model_calls=0),
                            fence=self._fence(),
                            parent_path=(),
                        )


if __name__ == "__main__":
    unittest.main()
