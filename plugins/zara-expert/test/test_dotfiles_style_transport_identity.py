import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.composition import CompositionError, InvocationFence, SharedSymbolicBudget
from zara_expert.dotfiles_style_expert import compose_dotfiles_style


class NonCanonicalText(str):
    pass


class PolicyTextHost:
    def __init__(self, policy):
        self.policy = policy
        self.calls = []

    def query(self, namespace, predicate, arguments):
        self.calls.append((namespace, predicate, arguments))
        if predicate == "style_policy":
            return {"ok": True, "results": [self.policy], "trace": []}
        return {"ok": True, "results": [], "trace": []}


class DotfilesStyleTransportIdentityTests(unittest.TestCase):
    @staticmethod
    def _fence():
        return InvocationFence(
            workspace_id="workspace:style-identity",
            workspace_generation=3,
            is_cancelled=lambda: False,
            is_current_generation=lambda workspace_id, generation: (
                workspace_id == "workspace:style-identity" and generation == 3
            ),
        )

    @staticmethod
    def _resolver(_rules, _context):
        raise AssertionError("resolver must not run for rejected transport identity")

    def test_direct_language_subclass_fails_before_host_dispatch(self):
        host = PolicyTextHost("style_policy(disabled,0,0)")
        with self.assertRaisesRegex(CompositionError, "language must be exact text"):
            compose_dotfiles_style(
                host,
                NonCanonicalText("nix"),
                resolver=self._resolver,
                budget=SharedSymbolicBudget(max_model_calls=0),
                fence=self._fence(),
            )
        self.assertEqual(host.calls, [])

    def test_registered_predicate_result_requires_exact_text_identity(self):
        host = PolicyTextHost(NonCanonicalText("style_policy(disabled,0,0)"))
        with self.assertRaisesRegex(CompositionError, "returned non-text"):
            compose_dotfiles_style(
                host,
                "nix",
                resolver=self._resolver,
                budget=SharedSymbolicBudget(max_model_calls=0),
                fence=self._fence(),
            )
        self.assertEqual(len(host.calls), 1)


if __name__ == "__main__":
    unittest.main()
