import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.composition import (
    CompositionError,
    DelegationRequest,
    InvocationFence,
    InvocationResult,
    MetaExpertComposer,
    SharedSymbolicBudget,
)


class DelegationRequestSnapshotTests(unittest.TestCase):
    def _fence(self):
        return InvocationFence(
            workspace_id="snapshot-test",
            workspace_generation=1,
            is_cancelled=lambda: False,
            is_current_generation=lambda workspace_id, generation: (
                workspace_id == "snapshot-test" and generation == 1
            ),
        )

    def test_mutating_source_mapping_after_validation_cannot_change_child_dispatch(self):
        source_input = {
            "route": {"expert": "safe"},
            "steps": ["inspect"],
        }
        delegation = DelegationRequest(
            expert_id="child",
            operation="query",
            input=source_input,
            reason="validated child",
        )
        parent_result = InvocationResult(
            status="succeeded",
            delegations=(delegation,),
        )

        source_input["route"]["expert"] = "drifted"
        source_input["steps"].append("mutated")

        child_inputs = []

        def invoke(expert_id, operation, input_data, *, budget, fence, parent_path):
            del operation, budget, fence, parent_path
            if expert_id == "root":
                return parent_result
            child_inputs.append(input_data)
            return InvocationResult(status="succeeded")

        MetaExpertComposer(invoke).invoke(
            "root",
            "query",
            {},
            budget=SharedSymbolicBudget(max_invocations=2),
            fence=self._fence(),
        )

        self.assertEqual(
            child_inputs,
            [{"route": {"expert": "safe"}, "steps": ["inspect"]}],
        )

    def test_stateful_text_subclasses_are_rejected_or_snapshotted_to_exact_strings(self):
        class StatefulText(str):
            pass

        cases = (
            {"expert_id": StatefulText("child"), "operation": "query", "reason": "reason", "field": "expert_id"},
            {"expert_id": "child", "operation": StatefulText("query"), "reason": "reason", "field": "operation"},
            {"expert_id": "child", "operation": "query", "reason": StatefulText("reason"), "field": "reason"},
        )

        for case in cases:
            field = case.pop("field")
            with self.subTest(field=field):
                try:
                    delegation = DelegationRequest(input={}, **case)
                except CompositionError:
                    continue
                self.assertIs(type(getattr(delegation, field)), str)


if __name__ == "__main__":
    unittest.main()
