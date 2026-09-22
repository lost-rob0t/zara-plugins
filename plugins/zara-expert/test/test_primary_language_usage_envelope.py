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


PRIMARY_EXPERT_IDS = (
    "zara:expert/prolog",
    "zara:expert/python",
    "zara:expert/nim",
)


class CoreLimits:
    def __init__(self, *, max_model_calls):
        self.max_model_calls = max_model_calls


class StaticRegistry:
    def __init__(self, result):
        self.result = result

    def invoke(self, handle, operation, payload, *, limits):
        del handle, operation, payload, limits
        return self.result


class PrimaryLanguageUsageEnvelopeTests(unittest.TestCase):
    @staticmethod
    def _fence():
        return InvocationFence(
            workspace_id="workspace-usage-envelope",
            workspace_generation=23,
            is_cancelled=lambda: False,
            is_current_generation=lambda _workspace, _generation: True,
        )

    @staticmethod
    def _payload():
        return {
            "source": "symbolic source",
            "source_generation": "generation:usage-envelope",
        }

    @staticmethod
    def _handler_result(usage):
        return {
            "verdict": "succeeded",
            "data": {"diagnostics": ["diagnostic(symbolic)."]},
            "evidence_refs": ["evidence:language:sha256:trusted"],
            "usage": usage,
            "effect_receipts": [],
        }

    @staticmethod
    def _core_result(usage):
        return SimpleNamespace(
            verdict=SimpleNamespace(value="succeeded"),
            data={"diagnostics": ["diagnostic(symbolic)."]},
            evidence_refs=("evidence:language:sha256:trusted",),
            usage=usage,
            effect_receipts=(),
        )

    def _direct_invoke(self, expert_id, usage):
        invoker = LanguageFamilyCompositionInvoker(object())
        with patch(
            "zara_expert.language_composition.make_language_expert_handler",
            return_value=lambda **_kwargs: self._handler_result(usage),
        ):
            return invoker(
                expert_id,
                "diagnose",
                self._payload(),
                budget=SharedSymbolicBudget(max_model_calls=0),
                fence=self._fence(),
                parent_path=(),
            )

    def _core_invoke(self, expert_id, usage):
        handle = SimpleNamespace(
            expert_id=expert_id,
            workspace="workspace-usage-envelope",
        )
        invoker = CoreLanguageFamilyCompositionInvoker(
            StaticRegistry(self._core_result(usage)),
            activation_for=lambda _expert_id, _fence, handle=handle: handle,
            limits_factory=CoreLimits,
        )
        return invoker(
            expert_id,
            "diagnose",
            self._payload(),
            budget=SharedSymbolicBudget(max_model_calls=0),
            fence=self._fence(),
            parent_path=(),
        )

    def test_direct_composition_accepts_only_explicit_integer_zero_provider_and_model_usage(self):
        for expert_id in PRIMARY_EXPERT_IDS:
            with self.subTest(expert_id=expert_id):
                result = self._direct_invoke(
                    expert_id,
                    {"provider_calls": 0, "model_calls": 0},
                )
                self.assertEqual(result.model_calls, 0)

    def test_core_composition_accepts_only_explicit_integer_zero_provider_and_model_usage(self):
        for expert_id in PRIMARY_EXPERT_IDS:
            with self.subTest(expert_id=expert_id):
                result = self._core_invoke(
                    expert_id,
                    {"provider_calls": 0, "model_calls": 0},
                )
                self.assertEqual(result.model_calls, 0)

    def test_direct_composition_rejects_missing_fake_or_extra_provider_proof(self):
        cases = (
            ({"model_calls": 0}, "attempted provider use"),
            ({"provider_calls": 1, "model_calls": 0}, "attempted provider use"),
            ({"provider_calls": 0.0, "model_calls": 0}, "attempted provider use"),
            ({"provider_calls": False, "model_calls": 0}, "attempted provider use"),
            ({"provider_calls": "0", "model_calls": 0}, "attempted provider use"),
            (
                {"provider_calls": 0, "model_calls": 0, "provider": "hidden-fallback"},
                "usage ledger contains unsupported fields",
            ),
        )
        for expert_id in PRIMARY_EXPERT_IDS:
            for usage, message in cases:
                with self.subTest(expert_id=expert_id, usage=usage):
                    with self.assertRaisesRegex(CompositionError, message):
                        self._direct_invoke(expert_id, usage)

    def test_core_composition_rejects_missing_fake_or_extra_provider_proof(self):
        cases = (
            ({"model_calls": 0}, "attempted provider use"),
            ({"provider_calls": 1, "model_calls": 0}, "attempted provider use"),
            ({"provider_calls": 0.0, "model_calls": 0}, "attempted provider use"),
            ({"provider_calls": False, "model_calls": 0}, "attempted provider use"),
            ({"provider_calls": "0", "model_calls": 0}, "attempted provider use"),
            (
                {"provider_calls": 0, "model_calls": 0, "provider": "hidden-fallback"},
                "usage ledger contains unsupported fields",
            ),
        )
        for expert_id in PRIMARY_EXPERT_IDS:
            for usage, message in cases:
                with self.subTest(expert_id=expert_id, usage=usage):
                    with self.assertRaisesRegex(CompositionError, message):
                        self._core_invoke(expert_id, usage)


if __name__ == "__main__":
    unittest.main()
