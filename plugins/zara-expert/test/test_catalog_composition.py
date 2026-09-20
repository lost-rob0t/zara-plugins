import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.catalog_composition import (
    CoreCatalogCompositionAdapter,
    CoreCatalogSelectedChildInvoker,
)
from zara_expert.composition import (
    CompositionError,
    InvocationFence,
    InvocationResult,
    MetaExpertComposer,
    SharedSymbolicBudget,
)
from zara_expert.core_catalog import CoreExpertCatalogAdapter


class FakeRegistry:
    def __init__(self):
        self.generation = 11
        self.runtime_generation = 5
        self.match_result = {
            "expert_id": "zara:expert/nix",
            "score": 1,
            "matched_keywords": ["nix"],
        }
        self.descriptor = {
            "expert_id": "zara:expert/nix",
            "protocol": "ZARA-EXPERT/1",
            "availability": "ready",
            "registry_generation": 0,
            "resource_limits": {"max_model_calls": 0},
        }

    def snapshot(self):
        return SimpleNamespace(
            generation=self.generation,
            runtime_generation=self.runtime_generation,
        )

    def match(self, goal_text):
        del goal_text
        return self.match_result

    def describe(self, expert_id):
        if expert_id != self.descriptor["expert_id"]:
            raise AssertionError(f"unexpected expert: {expert_id}")
        return dict(self.descriptor)

    def list_experts(self, principal, *, offset=0, limit=32):
        del principal
        return {
            "experts": [dict(self.descriptor)][offset : offset + limit],
            "total": 1,
            "offset": offset,
            "limit": limit,
            "registry_generation": self.generation,
        }


def live_fence():
    return InvocationFence(
        workspace_id="workspace:catalog-composition",
        workspace_generation=7,
        is_cancelled=lambda: False,
        is_current_generation=lambda workspace, generation: (
            workspace == "workspace:catalog-composition" and generation == 7
        ),
    )


class CoreCatalogCompositionAdapterTests(unittest.TestCase):
    def test_selection_flows_into_existing_composer_with_one_zero_model_budget(self):
        registry = FakeRegistry()
        calls = []

        def invoke(expert_id, operation, input_data, *, budget, fence, parent_path):
            del budget, fence
            calls.append((expert_id, operation, dict(input_data), parent_path))
            return InvocationResult(
                status="succeeded",
                data={"kind": "nix"},
                evidence=("ev:nix:inspect",),
                explanation="NixExpert inspected source through canonical Core",
                model_calls=0,
            )

        budget = SharedSymbolicBudget(max_invocations=2, max_model_calls=0)
        adapter = CoreCatalogCompositionAdapter(
            CoreExpertCatalogAdapter(registry, principal="user:catalog-composition"),
            MetaExpertComposer(invoke),
        )
        result = adapter.invoke(
            "inspect this nix flake",
            "inspect",
            {"source": "{ x = 1; }"},
            budget=budget,
            fence=live_fence(),
        )

        self.assertEqual(result.selection.expert_id, "zara:expert/nix")
        self.assertEqual(result.evidence.expert_id, "zara:expert/nix")
        self.assertEqual(result.evidence.reason, "root selection")
        self.assertEqual(result.evidence.evidence, ("ev:nix:inspect",))
        self.assertIn("canonical Zara ExpertRegistry selected", result.explanation)
        self.assertIn("NixExpert inspected", result.explanation)
        self.assertEqual(calls[0][0:2], ("zara:expert/nix", "inspect"))
        self.assertEqual(budget.invocations_used, 1)
        self.assertEqual(budget.max_model_calls, 0)
        self.assertEqual(budget.model_calls_used, 0)

    def test_delegated_child_is_revalidated_by_catalog_and_keeps_selection_explanation(self):
        registry = FakeRegistry()
        calls = []

        def invoke(expert_id, operation, input_data, *, budget, fence, parent_path):
            del budget, fence
            calls.append((expert_id, operation, dict(input_data), parent_path))
            return InvocationResult(
                status="succeeded",
                data={"kind": "nix"},
                evidence=("ev:nix:child",),
                explanation="NixExpert child completed through canonical Core",
                model_calls=0,
            )

        child = CoreCatalogSelectedChildInvoker(
            CoreExpertCatalogAdapter(registry, principal="user:catalog-child"),
            invoke,
            goal_for=lambda expert_id, operation, _input: (
                f"{operation} {expert_id.rsplit('/', 1)[-1]}"
            ),
        )
        budget = SharedSymbolicBudget(max_invocations=2, max_model_calls=0)
        result = child(
            "zara:expert/nix",
            "inspect",
            {"source": "{ x = 1; }"},
            budget=budget,
            fence=live_fence(),
            parent_path=("zara:expert/dotfiles.inspect",),
        )

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.evidence, ("ev:nix:child",))
        self.assertIn("canonical Zara ExpertRegistry selected", result.explanation)
        self.assertIn("NixExpert child completed", result.explanation)
        self.assertEqual(calls[0][0:2], ("zara:expert/nix", "inspect"))
        self.assertEqual(
            calls[0][3],
            ("zara:expert/dotfiles.inspect",),
        )
        self.assertEqual(budget.max_model_calls, 0)
        self.assertEqual(budget.model_calls_used, 0)

    def test_delegated_child_catalog_disagreement_fails_before_child_dispatch(self):
        registry = FakeRegistry()
        called = False

        def invoke(*args, **kwargs):
            nonlocal called
            called = True
            raise AssertionError("mismatched delegated child must not dispatch")

        child = CoreCatalogSelectedChildInvoker(
            CoreExpertCatalogAdapter(registry, principal="user:catalog-child"),
            invoke,
            goal_for=lambda expert_id, operation, _input: f"{operation} nix",
        )
        with self.assertRaisesRegex(CompositionError, "disagrees with delegated expert"):
            child(
                "zara:expert/bash",
                "inspect",
                {"source": "printf ok"},
                budget=SharedSymbolicBudget(max_model_calls=0),
                fence=live_fence(),
                parent_path=("zara:expert/dotfiles.inspect",),
            )
        self.assertFalse(called)

    def test_delegated_child_registry_change_rejects_late_evidence(self):
        registry = FakeRegistry()

        def invoke(expert_id, operation, input_data, *, budget, fence, parent_path):
            del expert_id, operation, input_data, budget, fence, parent_path
            registry.generation += 1
            return InvocationResult(
                status="succeeded",
                evidence=("ev:nix:late-child",),
                explanation="late child result that must not commit",
                model_calls=0,
            )

        child = CoreCatalogSelectedChildInvoker(
            CoreExpertCatalogAdapter(registry, principal="user:catalog-child"),
            invoke,
            goal_for=lambda expert_id, operation, _input: f"{operation} nix",
        )
        budget = SharedSymbolicBudget(max_model_calls=0)
        with self.assertRaisesRegex(
            CompositionError,
            "stale canonical delegated expert selection",
        ):
            child(
                "zara:expert/nix",
                "inspect",
                {"source": "{ x = 1; }"},
                budget=budget,
                fence=live_fence(),
                parent_path=("zara:expert/dotfiles.inspect",),
            )
        self.assertEqual(budget.model_calls_used, 0)

    def test_no_match_fails_before_composer_or_budget_use(self):
        registry = FakeRegistry()
        registry.match_result = None
        called = False

        def invoke(*args, **kwargs):
            nonlocal called
            called = True
            raise AssertionError("composer must not run on catalog miss")

        budget = SharedSymbolicBudget(max_model_calls=0)
        adapter = CoreCatalogCompositionAdapter(
            CoreExpertCatalogAdapter(registry, principal="user:catalog-composition"),
            MetaExpertComposer(invoke),
        )
        with self.assertRaisesRegex(CompositionError, "no symbolic match"):
            adapter.invoke(
                "unknown request",
                "inspect",
                {},
                budget=budget,
                fence=live_fence(),
            )
        self.assertFalse(called)
        self.assertEqual(budget.invocations_used, 0)
        self.assertEqual(budget.model_calls_used, 0)

    def test_nonzero_descriptor_model_budget_fails_before_composer(self):
        registry = FakeRegistry()
        registry.descriptor["resource_limits"] = {"max_model_calls": 1}
        called = False

        def invoke(*args, **kwargs):
            nonlocal called
            called = True
            raise AssertionError("composer must not run for model-capable selection")

        budget = SharedSymbolicBudget(max_model_calls=0)
        adapter = CoreCatalogCompositionAdapter(
            CoreExpertCatalogAdapter(registry, principal="user:catalog-composition"),
            MetaExpertComposer(invoke),
        )
        with self.assertRaisesRegex(CompositionError, "descriptor max_model_calls=0"):
            adapter.invoke(
                "inspect nix",
                "inspect",
                {},
                budget=budget,
                fence=live_fence(),
            )
        self.assertFalse(called)
        self.assertEqual(budget.invocations_used, 0)
        self.assertEqual(budget.model_calls_used, 0)

    def test_registry_change_after_expert_completion_rejects_late_evidence(self):
        registry = FakeRegistry()

        def invoke(expert_id, operation, input_data, *, budget, fence, parent_path):
            del expert_id, operation, input_data, budget, fence, parent_path
            registry.generation += 1
            return InvocationResult(
                status="succeeded",
                evidence=("ev:late",),
                explanation="late result that must not commit",
                model_calls=0,
            )

        budget = SharedSymbolicBudget(max_model_calls=0)
        adapter = CoreCatalogCompositionAdapter(
            CoreExpertCatalogAdapter(registry, principal="user:catalog-composition"),
            MetaExpertComposer(invoke),
        )
        with self.assertRaisesRegex(CompositionError, "stale canonical expert selection"):
            adapter.invoke(
                "inspect nix",
                "inspect",
                {},
                budget=budget,
                fence=live_fence(),
            )
        self.assertEqual(budget.invocations_used, 1)
        self.assertEqual(budget.model_calls_used, 0)


if __name__ == "__main__":
    unittest.main()
