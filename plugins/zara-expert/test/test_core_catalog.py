import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.composition import CompositionError, InvocationFence
from zara_expert.core_catalog import CoreExpertCatalogAdapter


class FakeRegistry:
    def __init__(self, *, count=3):
        self.generation = 11
        self.runtime_generation = 5
        self.descriptor_registry_generation = 0
        self.experts = [
            {
                "expert_id": f"zara:expert/e{index:03d}",
                "protocol": "ZARA-EXPERT/1",
                "availability": "ready",
            }
            for index in range(count)
        ]
        self.list_calls = []
        self.describe_calls = []
        self.match_calls = []
        self.match_result = {
            "expert_id": "zara:expert/e000",
            "score": 2,
            "matched_keywords": ["nix", "style"],
        }
        self.on_list = None
        self.on_describe = None
        self.on_match = None

    def snapshot(self):
        return SimpleNamespace(
            generation=self.generation,
            runtime_generation=self.runtime_generation,
        )

    def list_experts(self, principal, *, offset=0, limit=32):
        self.list_calls.append((principal, offset, limit))
        if self.on_list is not None:
            self.on_list(self)
        return {
            "experts": self.experts[offset : offset + limit],
            "total": len(self.experts),
            "offset": offset,
            "limit": limit,
            "registry_generation": self.generation,
        }

    def describe(self, expert_id):
        self.describe_calls.append(expert_id)
        if self.on_describe is not None:
            self.on_describe(self)
        for expert in self.experts:
            if expert["expert_id"] == expert_id:
                return {
                    **expert,
                    "registry_generation": self.descriptor_registry_generation,
                    "name": expert_id.rsplit("/", 1)[-1],
                }
        raise AssertionError(f"unknown fake expert: {expert_id}")

    def match(self, goal_text):
        self.match_calls.append(goal_text)
        if self.on_match is not None:
            self.on_match(self)
        return self.match_result


def live_fence(state):
    return InvocationFence(
        workspace_id="dotfiles",
        workspace_generation=7,
        is_cancelled=lambda: state["cancelled"],
        is_current_generation=lambda workspace, generation: (
            workspace == "dotfiles"
            and generation == 7
            and state["workspace_generation"] == 7
        ),
    )


class CoreExpertCatalogAdapterTests(unittest.TestCase):
    def test_list_reads_all_core_pages_without_caching_a_registry(self):
        registry = FakeRegistry(count=130)
        adapter = CoreExpertCatalogAdapter(registry, principal="operator")

        experts = adapter.list()

        self.assertEqual(len(experts), 130)
        self.assertEqual(experts[0]["expert_id"], "zara:expert/e000")
        self.assertEqual(experts[-1]["expert_id"], "zara:expert/e129")
        self.assertEqual(
            registry.list_calls,
            [("operator", 0, 128), ("operator", 128, 128)],
        )

    def test_select_explains_canonical_match_and_live_generation(self):
        registry = FakeRegistry()
        adapter = CoreExpertCatalogAdapter(registry, principal="operator")

        selection = adapter.select("check nix style")

        self.assertEqual(selection.expert_id, "zara:expert/e000")
        self.assertEqual(selection.score, 2)
        self.assertEqual(selection.matched_keywords, ("nix", "style"))
        self.assertEqual(selection.registry_generation, 11)
        self.assertEqual(selection.runtime_generation, 5)
        self.assertEqual(selection.descriptor["registry_generation"], 0)
        self.assertEqual(selection.descriptor["protocol"], "ZARA-EXPERT/1")
        self.assertIn("canonical Zara ExpertRegistry selected", selection.explanation)
        self.assertIn("score 2", selection.explanation)
        self.assertEqual(registry.match_calls, ["check nix style"])
        self.assertEqual(registry.describe_calls, ["zara:expert/e000"])

    def test_no_match_fails_closed_without_describe_or_fallback(self):
        registry = FakeRegistry()
        registry.match_result = None
        adapter = CoreExpertCatalogAdapter(registry, principal="operator")

        self.assertIsNone(adapter.match("unknown request"))
        with self.assertRaisesRegex(CompositionError, "no symbolic match"):
            adapter.select("unknown request")

        self.assertEqual(registry.describe_calls, [])
        self.assertEqual(registry.match_calls, ["unknown request", "unknown request"])

    def test_registry_generation_change_during_selection_is_rejected(self):
        registry = FakeRegistry()

        def replace_registry(fake):
            fake.generation += 1

        registry.on_describe = replace_registry
        adapter = CoreExpertCatalogAdapter(registry, principal="operator")

        with self.assertRaisesRegex(CompositionError, "stale expert registry generation"):
            adapter.select("check nix style")

    def test_runtime_generation_change_after_match_is_rejected(self):
        registry = FakeRegistry()

        def replace_runtime(fake):
            fake.runtime_generation += 1

        registry.on_describe = replace_runtime
        adapter = CoreExpertCatalogAdapter(registry, principal="operator")

        with self.assertRaisesRegex(CompositionError, "stale expert runtime generation"):
            adapter.select("check nix style")

    def test_catalog_duplicate_identity_fails_closed(self):
        registry = FakeRegistry(count=2)
        registry.experts[1] = dict(registry.experts[0])
        adapter = CoreExpertCatalogAdapter(registry, principal="operator")

        with self.assertRaisesRegex(CompositionError, "duplicate expert catalog entry"):
            adapter.list()

    def test_match_shape_rejects_bool_score_and_unsorted_keywords(self):
        registry = FakeRegistry()
        adapter = CoreExpertCatalogAdapter(registry, principal="operator")

        registry.match_result = {
            "expert_id": "zara:expert/e000",
            "score": True,
            "matched_keywords": ["nix"],
        }
        with self.assertRaisesRegex(CompositionError, "built-in integer"):
            adapter.select("nix")

        registry.match_result = {
            "expert_id": "zara:expert/e000",
            "score": 2,
            "matched_keywords": ["style", "nix"],
        }
        with self.assertRaisesRegex(CompositionError, "canonically sorted"):
            adapter.select("nix style")

    def test_unselectable_or_incompatible_descriptor_fails_closed(self):
        registry = FakeRegistry()
        adapter = CoreExpertCatalogAdapter(registry, principal="operator")

        registry.experts[0]["availability"] = "unavailable"
        with self.assertRaisesRegex(CompositionError, "no longer selectable"):
            adapter.select("nix")

        registry.experts[0]["availability"] = "ready"
        registry.experts[0]["protocol"] = "ZARA-EXPERT/2"
        with self.assertRaisesRegex(CompositionError, "not ZARA-EXPERT/1"):
            adapter.select("nix")

    def test_workspace_fence_blocks_cancelled_discovery_before_core_read(self):
        registry = FakeRegistry()
        adapter = CoreExpertCatalogAdapter(registry, principal="operator")
        state = {"cancelled": True, "workspace_generation": 7}

        with self.assertRaisesRegex(CompositionError, "cancelled"):
            adapter.list(fence=live_fence(state))

        self.assertEqual(registry.list_calls, [])

    def test_workspace_fence_rejects_late_stale_selection(self):
        registry = FakeRegistry()
        adapter = CoreExpertCatalogAdapter(registry, principal="operator")
        state = {"cancelled": False, "workspace_generation": 7}

        def stale_workspace(fake):
            del fake
            state["workspace_generation"] = 8

        registry.on_describe = stale_workspace
        with self.assertRaisesRegex(CompositionError, "stale workspace generation"):
            adapter.select("nix", fence=live_fence(state))


if __name__ == "__main__":
    unittest.main()
