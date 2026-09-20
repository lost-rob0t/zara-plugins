import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.composition import (
    CompositionError,
    DelegationRequest,
    DotfilesExpertSourceAdapter,
    ExpertCatalogAdapter,
    HostExpertInvoker,
    InvocationFence,
    InvocationResult,
    MetaExpertComposer,
    RegisteredPredicateBinding,
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
    def test_dotfiles_nix_style_chain_shares_budget_data_and_evidence(self):
        calls = []

        def invoke(expert_id, operation, input_data, *, budget, fence, parent_path):
            calls.append((expert_id, operation, budget, parent_path))
            if expert_id == "zara:expert/dotfiles":
                return InvocationResult(
                    status="succeeded",
                    data={"language": "nix"},
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
                    data={"parsed": True},
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
                data={"style": "project-nix"},
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
        self.assertTrue(all(item[2] is budget for item in calls))
        self.assertEqual(budget.invocations_used, 3)
        self.assertEqual(budget.evidence_used, 3)
        self.assertEqual(budget.model_calls_used, 0)
        self.assertEqual(tree.data, {"language": "nix"})
        self.assertEqual(tree.children[0].data, {"parsed": True})
        self.assertEqual(tree.children[0].children[0].data, {"style": "project-nix"})

    def test_dotfiles_bash_expert_chain_remains_zero_model(self):
        calls = []

        def invoke(expert_id, operation, input_data, *, budget, fence, parent_path):
            calls.append(expert_id)
            if expert_id == "zara:expert/dotfiles":
                return InvocationResult(
                    status="succeeded",
                    delegations=(
                        DelegationRequest(
                            "zara:expert/bash",
                            "inspect",
                            {"path": "bin/deploy"},
                            "shell source detected",
                        ),
                    ),
                )
            return InvocationResult(
                status="succeeded",
                data={"shell": "bash"},
                evidence=("bash:parsed",),
            )

        budget = SharedSymbolicBudget(max_invocations=2)
        tree = MetaExpertComposer(invoke).invoke(
            "zara:expert/dotfiles",
            "inspect",
            {"path": "bin/deploy"},
            budget=budget,
            fence=MutableFence().fence(),
        )
        self.assertEqual(calls, ["zara:expert/dotfiles", "zara:expert/bash"])
        self.assertEqual(tree.children[0].data["shell"], "bash")
        self.assertEqual(budget.model_calls_used, 0)

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

    def test_exact_repeat_is_rejected_as_no_progress_before_dispatch(self):
        calls = []

        def invoke(expert_id, operation, input_data, *, budget, fence, parent_path):
            calls.append((expert_id, operation, dict(input_data)))
            target = "b" if expert_id == "a" else "a"
            return InvocationResult(
                status="succeeded",
                delegations=(DelegationRequest(target, "query", {"step": 1}, "cycle"),),
            )

        with self.assertRaisesRegex(CompositionError, "made no progress"):
            MetaExpertComposer(invoke).invoke(
                "a",
                "query",
                {"step": 1},
                budget=SharedSymbolicBudget(),
                fence=MutableFence().fence(),
            )
        self.assertEqual([item[0] for item in calls], ["a", "b"])

    def test_same_expert_operation_with_changed_input_may_progress(self):
        calls = []

        def invoke(expert_id, operation, input_data, *, budget, fence, parent_path):
            calls.append(input_data["step"])
            if input_data["step"] == 1:
                return InvocationResult(
                    status="succeeded",
                    delegations=(
                        DelegationRequest(expert_id, operation, {"step": 2}, "refined input"),
                    ),
                )
            return InvocationResult(status="succeeded", data={"done": True})

        tree = MetaExpertComposer(invoke).invoke(
            "a",
            "query",
            {"step": 1},
            budget=SharedSymbolicBudget(max_invocations=2),
            fence=MutableFence().fence(),
        )
        self.assertEqual(calls, [1, 2])
        self.assertTrue(tree.children[0].data["done"])

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

    def test_nonzero_declared_model_usage_is_rejected(self):
        with self.assertRaisesRegex(CompositionError, "model use"):
            InvocationResult(status="succeeded", model_calls=1)
        with self.assertRaisesRegex(ValueError, "max_model_calls=0"):
            SharedSymbolicBudget(max_model_calls=1)

    def test_invoker_cannot_mutate_shared_model_call_ledger(self):
        calls = []

        def invoke(expert_id, operation, input_data, *, budget, fence, parent_path):
            calls.append(expert_id)
            budget.model_calls_used = 1
            return InvocationResult(
                status="succeeded",
                delegations=(DelegationRequest("child", "query", {}, "must not run"),),
            )

        budget = SharedSymbolicBudget()
        with self.assertRaisesRegex(
            CompositionError,
            "mutated shared symbolic budget: model_calls_used",
        ):
            MetaExpertComposer(invoke).invoke(
                "parent", "query", {}, budget=budget, fence=MutableFence().fence()
            )
        self.assertEqual(calls, ["parent"])
        self.assertEqual(budget.max_model_calls, 0)
        self.assertEqual(budget.model_calls_used, 0)

    def test_non_inert_input_fails_before_invoker(self):
        calls = []

        def invoke(*args, **kwargs):
            calls.append(True)
            return InvocationResult(status="succeeded")

        with self.assertRaisesRegex(CompositionError, "unsupported value"):
            MetaExpertComposer(invoke).invoke(
                "a",
                "query",
                {"callable": object()},
                budget=SharedSymbolicBudget(),
                fence=MutableFence().fence(),
            )
        self.assertEqual(calls, [])

    def test_style_precedence_and_provenance_are_deterministic(self):
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

        effective = resolve_style(overlays, language="nix", fence=MutableFence().fence())
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

    def test_host_adapter_uses_registered_predicate_binding_not_user_goal(self):
        class Host:
            def __init__(self):
                self.calls = []

            def query(self, namespace, predicate, arguments):
                self.calls.append((namespace, predicate, tuple(arguments)))
                return {"ok": True, "results": [{"proved": True}], "trace": ["fact:x"]}

        host = Host()
        invoker = HostExpertInvoker(
            host,
            binding_for=lambda expert_id, operation, input_data: RegisteredPredicateBinding(
                namespace="dotfiles",
                predicate="valid",
                arguments=(input_data["subject"],),
            ),
        )
        budget = SharedSymbolicBudget()
        tree = MetaExpertComposer(invoker).invoke(
            "zara:expert/dotfiles",
            "verify",
            {"subject": "config", "predicate": "shell", "goal": "halt"},
            budget=budget,
            fence=MutableFence().fence(),
        )
        self.assertEqual(host.calls, [("dotfiles", "valid", ("config",))])
        self.assertEqual(tree.evidence, ("fact:x",))
        self.assertEqual(tree.data["results"][0]["proved"], True)
        self.assertEqual(budget.model_calls_used, 0)

    def test_host_adapter_supports_registered_explain_binding(self):
        class Host:
            def explain(self, namespace, predicate, arguments):
                return {"ok": True, "results": [], "trace": ["rule:why"]}

        invoker = HostExpertInvoker(
            Host(),
            binding_for=lambda expert_id, operation, input_data: RegisteredPredicateBinding(
                "style", "why_style", (input_data["language"],), host_operation="explain"
            ),
        )
        tree = MetaExpertComposer(invoker).invoke(
            "zara:expert/style",
            "explain",
            {"language": "nix"},
            budget=SharedSymbolicBudget(),
            fence=MutableFence().fence(),
        )
        self.assertEqual(tree.evidence, ("rule:why",))

    def test_dotfiles_source_adapter_is_transport_neutral_and_fenced(self):
        calls = []
        adapter = DotfilesExpertSourceAdapter(
            list_package_names=lambda workspace, generation: (
                calls.append(("list", workspace, generation))
                or ("sysadmin", "emacs", "git")
            ),
            read_package_text=lambda workspace, generation, package, path: (
                calls.append(("read", workspace, generation, package, path))
                or "can_handle(dotfiles)."
            ),
        )
        fence = MutableFence().fence()
        self.assertEqual(adapter.list_packages(fence=fence), ("emacs", "git", "sysadmin"))
        resource = adapter.read_resource("git", "kb/expert.pl", fence=fence)
        self.assertEqual(resource.source_reference, ".zara/experts/git/kb/expert.pl")
        self.assertEqual(resource.workspace_id, "dotfiles")
        self.assertEqual(resource.content, "can_handle(dotfiles).")
        self.assertNotIn("/home/", resource.source_reference)
        self.assertEqual(calls[0], ("list", "dotfiles", 7))

    def test_dotfiles_source_adapter_rejects_traversal_before_reader(self):
        calls = []
        adapter = DotfilesExpertSourceAdapter(
            list_package_names=lambda workspace, generation: (),
            read_package_text=lambda *args: calls.append(args) or "bad",
        )
        for path in ("../secret.pl", "kb/../../secret.pl", "/etc/passwd"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(CompositionError, "escapes package"):
                    adapter.read_resource("git", path, fence=MutableFence().fence())
        self.assertEqual(calls, [])

    def test_dotfiles_source_adapter_rejects_case_collision_or_invalid_case(self):
        adapter = DotfilesExpertSourceAdapter(
            list_package_names=lambda workspace, generation: ("git", "Git"),
            read_package_text=lambda *args: "",
        )
        with self.assertRaises(CompositionError):
            adapter.list_packages(fence=MutableFence().fence())

    def test_dotfiles_source_adapter_fences_stale_read_completion(self):
        state = MutableFence()

        def read(*args):
            state.generation = 8
            return "late"

        adapter = DotfilesExpertSourceAdapter(
            list_package_names=lambda workspace, generation: ("git",),
            read_package_text=read,
        )
        with self.assertRaisesRegex(CompositionError, "stale workspace generation"):
            adapter.read_resource("git", "kb/expert.pl", fence=state.fence())


if __name__ == "__main__":
    unittest.main()
