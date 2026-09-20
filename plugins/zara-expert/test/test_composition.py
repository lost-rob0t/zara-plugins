import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.composition import (
    CompositionError,
    DelegationRequest,
    ExpertCatalogAdapter,
    HostExpertInvoker,
    InvocationFence,
    InvocationResult,
    MetaExpertComposer,
    SharedSymbolicBudget,
    StyleOverlay,
    StyleScope,
    resolve_style,
)


class MutableFence:
    def __init__(self):
        self.cancelled = False
        self.generation = 7

    def fence(self):
        return InvocationFence(
            workspace_id="dotfiles",
            workspace_generation=7,
            is_cancelled=lambda: self.cancelled,
            is_current_generation=lambda workspace, generation: (
                workspace == "dotfiles" and generation == self.generation
            ),
        )


class CompositionTests(unittest.TestCase):
    def test_dotfiles_nix_style_chain_shares_budget_and_evidence(self):
        calls = []

        def invoke(expert_id, operation, input_data, *, budget, fence, parent_path):
            calls.append((expert_id, budget, parent_path))
            if expert_id == "zara:expert/dotfiles":
                return InvocationResult(
                    status="succeeded",
                    evidence=("dotfiles:project",),
                    delegations=(
                        DelegationRequest(
                            "zara:expert/nix",
                            "inspect",
                            {"path": "flake.nix"},
                            "Nix source detected",
                        ),
                    ),
                )
            if expert_id == "zara:expert/nix":
                return InvocationResult(
                    status="succeeded",
                    evidence=("nix:parsed",),
                    delegations=(
                        DelegationRequest(
                            "zara:expert/style",
                            "style_check",
                            {"language": "nix"},
                            "apply effective project style",
                        ),
                    ),
                )
            return InvocationResult(
                status="succeeded",
                evidence=("style:project-language",),
                explanation="project Nix style selected",
            )

        budget = SharedSymbolicBudget(max_invocations=3, max_depth=2, max_evidence=3)
        tree = MetaExpertComposer(invoke).invoke(
            "zara:expert/dotfiles",
            "inspect",
            {"path": "flake.nix"},
            budget=budget,
            fence=MutableFence().fence(),
        )

        self.assertEqual([item[0] for item in calls], [
            "zara:expert/dotfiles",
            "zara:expert/nix",
            "zara:expert/style",
        ])
        self.assertTrue(all(item[1] is budget for item in calls))
        self.assertEqual(budget.invocations_used, 3)
        self.assertEqual(budget.evidence_used, 3)
        self.assertEqual(budget.model_calls_used, 0)
        self.assertEqual(tree.children[0].children[0].explanation, "project Nix style selected")

    def test_nested_budget_cannot_reset(self):
        def invoke(expert_id, operation, input_data, *, budget, fence, parent_path):
            next_id = {"a": "b", "b": "c"}.get(expert_id)
            delegations = ()
            if next_id:
                delegations = (DelegationRequest(next_id, "query", {}, "next"),)
            return InvocationResult(status="succeeded", delegations=delegations)

        budget = SharedSymbolicBudget(max_invocations=2, max_depth=8)
        with self.assertRaisesRegex(CompositionError, "invocation budget exceeded"):
            MetaExpertComposer(invoke).invoke(
                "a", "query", {}, budget=budget, fence=MutableFence().fence()
            )
        self.assertEqual(budget.invocations_used, 2)

    def test_cycle_fails_closed_without_extra_invocation(self):
        calls = []

        def invoke(expert_id, operation, input_data, *, budget, fence, parent_path):
            calls.append(expert_id)
            target = "b" if expert_id == "a" else "a"
            return InvocationResult(
                status="succeeded",
                delegations=(DelegationRequest(target, "query", {}, "cycle"),),
            )

        with self.assertRaisesRegex(CompositionError, "a -> b -> a"):
            MetaExpertComposer(invoke).invoke(
                "a",
                "query",
                {},
                budget=SharedSymbolicBudget(),
                fence=MutableFence().fence(),
            )
        self.assertEqual(calls, ["a", "b"])

    def test_cancellation_fences_child_dispatch(self):
        state = MutableFence()
        calls = []

        def invoke(expert_id, operation, input_data, *, budget, fence, parent_path):
            calls.append(expert_id)
            if expert_id == "parent":
                state.cancelled = True
                return InvocationResult(
                    status="succeeded",
                    delegations=(DelegationRequest("child", "query", {}, "late"),),
                )
            return InvocationResult(status="succeeded")

        with self.assertRaisesRegex(CompositionError, "cancelled"):
            MetaExpertComposer(invoke).invoke(
                "parent",
                "query",
                {},
                budget=SharedSymbolicBudget(),
                fence=state.fence(),
            )
        self.assertEqual(calls, ["parent"])

    def test_stale_generation_rejects_late_completion(self):
        state = MutableFence()

        def invoke(expert_id, operation, input_data, *, budget, fence, parent_path):
            state.generation = 8
            return InvocationResult(status="succeeded", evidence=("late",))

        budget = SharedSymbolicBudget()
        with self.assertRaisesRegex(CompositionError, "stale workspace generation"):
            MetaExpertComposer(invoke).invoke(
                "a", "query", {}, budget=budget, fence=state.fence()
            )
        self.assertEqual(budget.evidence_used, 0)

    def test_nonzero_model_usage_is_rejected(self):
        with self.assertRaisesRegex(CompositionError, "model use"):
            InvocationResult(status="succeeded", model_calls=1)
        with self.assertRaisesRegex(ValueError, "max_model_calls=0"):
            SharedSymbolicBudget(max_model_calls=1)

    def test_style_precedence_and_provenance_are_deterministic(self):
        state = MutableFence()
        overlays = [
            StyleOverlay(
                StyleScope.PROJECT_LANGUAGE,
                {"indent": 2, "formatter": "alejandra"},
                "repo/.zara/style/languages/nix.pl",
                "p1",
                language="nix",
                workspace_id="dotfiles",
                workspace_generation=7,
            ),
            StyleOverlay(
                StyleScope.USER_GLOBAL,
                {"indent": 4, "quotes": "double"},
                "~/.config/zarathushtra/style/global.pl",
                "u1",
            ),
            StyleOverlay(
                StyleScope.USER_LANGUAGE,
                {"indent": 3},
                "~/.config/zarathushtra/style/languages/nix.pl",
                "u2",
                language="nix",
            ),
            StyleOverlay(
                StyleScope.PROJECT_GLOBAL,
                {"quotes": "single"},
                "repo/.zara/style/project.pl",
                "p0",
                workspace_id="dotfiles",
                workspace_generation=7,
            ),
            StyleOverlay(
                StyleScope.SESSION,
                {"indent": 8},
                "session:42",
                "s1",
            ),
        ]

        effective = resolve_style(overlays, language="nix", fence=state.fence())
        self.assertEqual(effective.values, {
            "indent": 8,
            "quotes": "single",
            "formatter": "alejandra",
        })
        self.assertEqual(
            effective.provenance["formatter"],
            ("project_language", "repo/.zara/style/languages/nix.pl", "p1"),
        )
        self.assertEqual(effective.provenance["indent"][0], "session")

    def test_style_overlay_cannot_widen_authority(self):
        with self.assertRaisesRegex(CompositionError, "cannot change authority"):
            StyleOverlay(
                StyleScope.PROJECT_GLOBAL,
                {"capabilities": ["shell"]},
                "repo/.zara/style/project.pl",
                "p0",
                workspace_id="dotfiles",
                workspace_generation=7,
            )

    def test_stale_project_style_fails_closed(self):
        with self.assertRaisesRegex(CompositionError, "stale project style generation"):
            resolve_style(
                [
                    StyleOverlay(
                        StyleScope.PROJECT_GLOBAL,
                        {"indent": 2},
                        "repo/.zara/style/project.pl",
                        "old",
                        workspace_id="dotfiles",
                        workspace_generation=6,
                    )
                ],
                language="nix",
                fence=MutableFence().fence(),
            )

    def test_catalog_adapter_does_not_create_or_cache_registry(self):
        calls = []
        adapter = ExpertCatalogAdapter(
            list_experts=lambda: calls.append("list") or ({"expert_id": "a"},),
            describe_expert=lambda expert_id: calls.append(("describe", expert_id))
            or {"expert_id": expert_id},
            match_experts=lambda request: calls.append(("match", dict(request)))
            or ({"expert_id": "a", "reason": "symbolic"},),
        )
        self.assertEqual(adapter.list()[0]["expert_id"], "a")
        self.assertEqual(adapter.describe("a")["expert_id"], "a")
        self.assertEqual(adapter.match({"kind": "nix"})[0]["reason"], "symbolic")
        self.assertEqual(len(calls), 3)

    def test_host_adapter_uses_existing_host_and_canonical_identity_resolver(self):
        class Host:
            def __init__(self):
                self.calls = []

            def explain(self, namespace, goal):
                self.calls.append((namespace, goal))
                return {"ok": True, "results": [{"proved": True}], "trace": ["fact:x"]}

        host = Host()
        invoker = HostExpertInvoker(host, namespace_for_id=lambda expert_id: "dotfiles")
        budget = SharedSymbolicBudget()
        tree = MetaExpertComposer(invoker).invoke(
            "zara:expert/dotfiles",
            "explain",
            {"goal": "valid(config)"},
            budget=budget,
            fence=MutableFence().fence(),
        )
        self.assertEqual(host.calls, [("dotfiles", "valid(config)")])
        self.assertEqual(tree.evidence, ("fact:x",))
        self.assertEqual(budget.model_calls_used, 0)


if __name__ == "__main__":
    unittest.main()
