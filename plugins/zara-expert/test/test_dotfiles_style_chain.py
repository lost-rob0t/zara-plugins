import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert import DotfilesStyleLanguageChainInvoker
from zara_expert.composition import (
    CompositionError,
    DelegationRequest,
    InvocationFence,
    InvocationResult,
    MetaExpertComposer,
    SharedSymbolicBudget,
)
from zara_expert.dotfiles_style_expert import STYLE_EXPERT_ID


class RecordingInvoker:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(
        self,
        expert_id,
        operation,
        input_data,
        *,
        budget,
        fence,
        parent_path,
    ):
        self.calls.append((expert_id, operation, dict(input_data), parent_path))
        budget.assert_zero_model_usage()
        fence.check()
        return self.result


class StatefulInvocationResult(InvocationResult):
    """Hide a duplicate delegation during validation, then reveal it on projection."""

    def __init__(self):
        super().__init__(status="succeeded", model_calls=0)
        object.__setattr__(self, "_delegation_reads", 0)
        object.__setattr__(
            self,
            "_hidden_delegations",
            (
                DelegationRequest(
                    expert_id=STYLE_EXPERT_ID,
                    operation="resolve",
                    input={"language": "nix"},
                    reason="stateful duplicate delegation",
                ),
            ),
        )

    def __getattribute__(self, name):
        if name == "delegations":
            try:
                reads = object.__getattribute__(self, "_delegation_reads")
            except AttributeError:
                return object.__getattribute__(self, "__dict__").get("delegations", ())
            object.__setattr__(self, "_delegation_reads", reads + 1)
            if reads == 0:
                return ()
            return object.__getattribute__(self, "_hidden_delegations")
        return super().__getattribute__(name)


class StatefulDelegationRequest(DelegationRequest):
    """A delegation-shaped object whose target changes after first observation."""

    def __init__(self):
        super().__init__(
            expert_id="zara:expert/other",
            operation="inspect",
            input={},
            reason="stateful delegation target",
        )
        object.__setattr__(self, "_expert_id_reads", 0)

    def __getattribute__(self, name):
        if name == "expert_id":
            try:
                reads = object.__getattribute__(self, "_expert_id_reads")
            except AttributeError:
                return object.__getattribute__(self, "__dict__").get(
                    "expert_id", "zara:expert/other"
                )
            object.__setattr__(self, "_expert_id_reads", reads + 1)
            if reads == 0:
                return "zara:expert/other"
            return STYLE_EXPERT_ID
        return super().__getattribute__(name)


class DotfilesStyleLanguageChainTests(unittest.TestCase):
    def setUp(self):
        self.fence = InvocationFence(
            workspace_id="workspace:chain",
            workspace_generation=9,
            is_cancelled=lambda: False,
            is_current_generation=lambda workspace_id, generation: (
                workspace_id == "workspace:chain" and generation == 9
            ),
        )

    def test_successful_nix_inspect_delegates_to_style_in_same_composer_budget(self):
        language = RecordingInvoker(
            InvocationResult(
                status="succeeded",
                data={"result": {"language": "nix"}},
                evidence=("language:nix",),
                explanation="canonical NixExpert inspect",
                model_calls=0,
            )
        )
        style = RecordingInvoker(
            InvocationResult(
                status="succeeded",
                data={"language": "nix", "effective": []},
                evidence=("style:nix",),
                explanation="canonical StyleExpert resolution",
                model_calls=0,
            )
        )
        composer = MetaExpertComposer(DotfilesStyleLanguageChainInvoker(language, style))
        budget = SharedSymbolicBudget(
            max_invocations=2,
            max_depth=1,
            max_evidence=8,
            max_model_calls=0,
        )

        tree = composer.invoke(
            "zara:expert/nix",
            "inspect",
            {"source": "{ x = 1; }", "source_generation": "generation-9"},
            budget=budget,
            fence=self.fence,
        )

        self.assertEqual(tree.expert_id, "zara:expert/nix")
        self.assertEqual(tree.status, "succeeded")
        self.assertEqual(len(tree.children), 1)
        child = tree.children[0]
        self.assertEqual(child.expert_id, STYLE_EXPERT_ID)
        self.assertEqual(child.operation, "resolve")
        self.assertEqual(child.reason, "NixExpert inspect succeeded; resolve canonical Dotfiles style")
        self.assertEqual(child.evidence, ("style:nix",))
        self.assertEqual(language.calls[0][3], ())
        self.assertEqual(style.calls[0][3], ("zara:expert/nix.inspect",))
        self.assertEqual(budget.invocations_used, 2)
        self.assertEqual(budget.evidence_used, 2)
        self.assertEqual(budget.max_model_calls, 0)
        self.assertEqual(budget.model_calls_used, 0)

    def test_bash_style_delegation_preserves_existing_child_delegations(self):
        language = RecordingInvoker(
            InvocationResult(
                status="succeeded",
                delegations=(
                    DelegationRequest(
                        expert_id="zara:expert/other",
                        operation="inspect",
                        input={},
                        reason="existing delegation",
                    ),
                ),
                model_calls=0,
            )
        )
        style = RecordingInvoker(InvocationResult(status="succeeded", model_calls=0))
        chain = DotfilesStyleLanguageChainInvoker(language, style)
        result = chain(
            "zara:expert/bash",
            "inspect",
            {"source": "printf ok", "source_generation": "generation-9"},
            budget=SharedSymbolicBudget(max_model_calls=0),
            fence=self.fence,
            parent_path=(),
        )
        self.assertEqual(len(result.delegations), 2)
        self.assertEqual(result.delegations[0].expert_id, "zara:expert/other")
        self.assertEqual(result.delegations[1].expert_id, STYLE_EXPERT_ID)
        self.assertEqual(result.delegations[1].input, {"language": "bash"})

    def test_failed_or_noninspect_language_result_does_not_invent_style_delegation(self):
        for status, operation in (("failed", "inspect"), ("succeeded", "style.rules")):
            with self.subTest(status=status, operation=operation):
                language = RecordingInvoker(InvocationResult(status=status, model_calls=0))
                style = RecordingInvoker(InvocationResult(status="succeeded", model_calls=0))
                chain = DotfilesStyleLanguageChainInvoker(language, style)
                result = chain(
                    "zara:expert/nix",
                    operation,
                    {},
                    budget=SharedSymbolicBudget(max_model_calls=0),
                    fence=self.fence,
                    parent_path=(),
                )
                self.assertEqual(result.delegations, ())
                self.assertEqual(style.calls, [])

    def test_style_route_is_fixed_and_unknown_experts_fail_closed(self):
        language = RecordingInvoker(InvocationResult(status="succeeded", model_calls=0))
        style = RecordingInvoker(
            InvocationResult(
                status="succeeded",
                data={"language": "nix"},
                model_calls=0,
            )
        )
        chain = DotfilesStyleLanguageChainInvoker(language, style)
        budget = SharedSymbolicBudget(max_model_calls=0)
        result = chain(
            STYLE_EXPERT_ID,
            "resolve",
            {"language": "nix"},
            budget=budget,
            fence=self.fence,
            parent_path=("zara:expert/nix.inspect",),
        )
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(language.calls, [])
        self.assertEqual(len(style.calls), 1)
        with self.assertRaisesRegex(CompositionError, "unsupported Dotfiles style-chain expert"):
            chain(
                "zara:expert/python",
                "inspect",
                {},
                budget=SharedSymbolicBudget(max_model_calls=0),
                fence=self.fence,
                parent_path=(),
            )

    def test_style_chain_rejects_stateful_invocation_result_subclass_before_projection(self):
        language = RecordingInvoker(StatefulInvocationResult())
        style = RecordingInvoker(InvocationResult(status="succeeded", model_calls=0))
        chain = DotfilesStyleLanguageChainInvoker(language, style)

        with self.assertRaisesRegex(CompositionError, "invalid result"):
            chain(
                "zara:expert/nix",
                "inspect",
                {"source": "{ x = 1; }", "source_generation": "generation-9"},
                budget=SharedSymbolicBudget(max_model_calls=0),
                fence=self.fence,
                parent_path=(),
            )

        self.assertEqual(style.calls, [])

    def test_style_chain_rejects_stateful_delegation_request_subclass_before_projection(self):
        language = RecordingInvoker(
            InvocationResult(
                status="succeeded",
                delegations=(StatefulDelegationRequest(),),
                model_calls=0,
            )
        )
        style = RecordingInvoker(InvocationResult(status="succeeded", model_calls=0))
        chain = DotfilesStyleLanguageChainInvoker(language, style)

        with self.assertRaisesRegex(CompositionError, "invalid delegation request"):
            chain(
                "zara:expert/nix",
                "inspect",
                {"source": "{ x = 1; }", "source_generation": "generation-9"},
                budget=SharedSymbolicBudget(max_model_calls=0),
                fence=self.fence,
                parent_path=(),
            )

        self.assertEqual(style.calls, [])


if __name__ == "__main__":
    unittest.main()
