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

    def test_direct_composition_rejects_provider_shaped_usage_metadata(self):
        invoker = LanguageFamilyCompositionInvoker(object())

        for expert_id in PRIMARY_EXPERT_IDS:
            with self.subTest(expert_id=expert_id):
                fake_handler = lambda **_kwargs: {
                    "verdict": "succeeded",
                    "data": {"diagnostics": ["diagnostic(symbolic)."]},
                    "evidence_refs": ["evidence:language:sha256:trusted"],
                    "usage": {
                        "model_calls": 0,
                        "provider_calls": 1,
                        "provider": "hidden-fallback",
                    },
                    "effect_receipts": [],
                }
                with patch(
                    "zara_expert.language_composition.make_language_expert_handler",
                    return_value=fake_handler,
                ):
                    with self.assertRaisesRegex(
                        CompositionError,
                        "usage ledger contains unsupported fields",
                    ):
                        invoker(
                            expert_id,
                            "diagnose",
                            self._payload(),
                            budget=SharedSymbolicBudget(max_model_calls=0),
                            fence=self._fence(),
                            parent_path=(),
                        )

    def test_core_composition_rejects_provider_shaped_usage_metadata(self):
        for expert_id in PRIMARY_EXPERT_IDS:
            with self.subTest(expert_id=expert_id):
                result = SimpleNamespace(
                    verdict=SimpleNamespace(value="succeeded"),
                    data={"diagnostics": ["diagnostic(symbolic)."]},
                    evidence_refs=("evidence:language:sha256:trusted",),
                    usage={
                        "model_calls": 0,
                        "provider_calls": 1,
                        "provider": "hidden-fallback",
                    },
                    effect_receipts=(),
                )
                registry = StaticRegistry(result)
                handle = SimpleNamespace(
                    expert_id=expert_id,
                    workspace="workspace-usage-envelope",
                )
                invoker = CoreLanguageFamilyCompositionInvoker(
                    registry,
                    activation_for=lambda _expert_id, _fence, handle=handle: handle,
                    limits_factory=CoreLimits,
                )

                with self.assertRaisesRegex(
                    CompositionError,
                    "usage ledger contains unsupported fields",
                ):
                    invoker(
                        expert_id,
                        "diagnose",
                        self._payload(),
                        budget=SharedSymbolicBudget(max_model_calls=0),
                        fence=self._fence(),
                        parent_path=(),
                    )


if __name__ == "__main__":
    unittest.main()
