import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "zara-expert"
sys.path.insert(0, str(PLUGIN_ROOT / "lib"))

from zara_expert.backend import SwiplBackend
from zara_expert.composition import InvocationFence, SharedSymbolicBudget
from zara_expert.domain import ExpertHost
from zara_expert.dotfiles_style_expert import (
    STYLE_EXPERT_ID,
    compose_dotfiles_style,
    register_dotfiles_style_expert,
)


class DotfilesStyleExpertE2E(unittest.TestCase):
    def setUp(self):
        root_value = os.environ.get("ZARA_DOTFILES_ROOT")
        if not root_value:
            self.skipTest("ZARA_DOTFILES_ROOT is required")
        if not SwiplBackend.available():
            self.skipTest("SWI-Prolog is required")

        self.dotfiles_root = Path(root_value).resolve()
        self.producer = self.dotfiles_root / ".zara" / "experts" / "style" / "kb" / "expert.pl"
        self.assertTrue(self.producer.is_file(), self.producer)
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.host = ExpertHost(
            SwiplBackend(),
            state_root=Path(self.tempdir.name) / "expert-state",
        )
        register_dotfiles_style_expert(self.host, self.producer)
        self.current_generation = 23
        self.cancelled = False

    def _fence(self):
        return InvocationFence(
            workspace_id="workspace:dotfiles-e2e",
            workspace_generation=23,
            is_cancelled=lambda: self.cancelled,
            is_current_generation=lambda workspace_id, generation: (
                workspace_id == "workspace:dotfiles-e2e"
                and generation == self.current_generation
            ),
        )

    @staticmethod
    def _identity_resolver(rules, context):
        """Transport fixture; upstream Prolog-RLM contract is gated separately in CI."""

        decisions = [
            {
                "check": rule["check"],
                "winner": rule["id"],
                "winner_scope": rule["scope"],
                "winner_revision": rule["revision"],
                "winner_provenance": rule["provenance"],
                "shadowed": [],
                "shadowed_provenance": [],
            }
            for rule in rules
        ]
        return {
            "effective": list(rules),
            "decisions": decisions,
            "project_id": context["project_id"],
            "project_generation": context["project_generation"],
            "language": context["language"],
            "usage": {"model_calls": 0},
        }

    def test_real_nix_and_bash_producer_stays_offline_zero_model_and_fenced(self):
        for language in ("nix", "bash"):
            with self.subTest(language=language):
                budget = SharedSymbolicBudget(max_model_calls=0)
                fence = self._fence()
                result = compose_dotfiles_style(
                    self.host,
                    language,
                    resolver=self._identity_resolver,
                    budget=budget,
                    fence=fence,
                )

                self.assertEqual(result.expert_id, STYLE_EXPERT_ID)
                self.assertTrue(result.rules)
                self.assertTrue(
                    all(rule["project_id"] == fence.workspace_id for rule in result.rules)
                )
                self.assertTrue(
                    all(
                        rule["project_generation"] == fence.workspace_generation
                        for rule in result.rules
                    )
                )
                self.assertIn("style-expert:provider_policy=disabled", result.evidence)
                self.assertIn("style-expert:max_model_calls=0", result.evidence)
                self.assertIn("style-expert:model_calls=0", result.evidence)
                self.assertEqual(budget.max_model_calls, 0)
                self.assertEqual(budget.model_calls_used, 0)

                by_check = {rule["check"]: rule for rule in result.rules}
                self.assertFalse(
                    by_check["expert_runtime.hidden_model_fallback"]["preferred"]
                )
                self.assertFalse(by_check["expert_runtime.providers_required"]["preferred"])
                if language == "nix":
                    self.assertEqual(
                        by_check["formatting.formatter"]["preferred"],
                        "nixfmt-rfc-style",
                    )
                else:
                    self.assertIn("verification", " ".join(by_check))

    def test_cancellation_rejects_before_registered_predicate_dispatch(self):
        self.cancelled = True
        budget = SharedSymbolicBudget(max_model_calls=0)
        with self.assertRaisesRegex(Exception, "expert invocation cancelled"):
            compose_dotfiles_style(
                self.host,
                "nix",
                resolver=self._identity_resolver,
                budget=budget,
                fence=self._fence(),
            )
        self.assertEqual(budget.model_calls_used, 0)


if __name__ == "__main__":
    unittest.main()
