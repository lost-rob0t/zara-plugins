import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOTFILES_ROOT = os.environ.get("ZARA_DOTFILES_ROOT")
EXPECTED_DOTFILES_COMMIT = "1b93e01f3482e49a853f651eb28c21eb1d9cad0e"
ZARA_EXPERT_LIB = REPO_ROOT / "plugins" / "zara-expert" / "lib"
sys.path.insert(0, str(ZARA_EXPERT_LIB))

from zara_expert.backend import SwiplBackend
from zara_expert.composition import (
    CompositionError,
    InvocationFence,
    MetaExpertComposer,
    SharedSymbolicBudget,
)
from zara_expert.domain import ExpertHost
from zara_expert.language_composition import LanguageFamilyCompositionInvoker
from zara_expert.language_family import register_language_family
from zara_expert.language_source_contract import validate_language_source_contracts


def _run(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


@unittest.skipUnless(DOTFILES_ROOT, "exact Dotfiles checkout not provided")
class NixBashSharedCompositionE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for shared composition E2E")
        revision = _run("git", "rev-parse", "HEAD", cwd=cls.dotfiles_root)
        if revision.returncode != 0:
            raise AssertionError(f"cannot resolve Dotfiles checkout: {revision.stderr}")
        if revision.stdout.strip() != EXPECTED_DOTFILES_COMMIT:
            raise AssertionError(
                "Dotfiles checkout must match pinned Nix/Bash producer: "
                f"expected {EXPECTED_DOTFILES_COMMIT}, got {revision.stdout.strip()}"
            )
        cls.sources = {
            "nix": [
                cls.dotfiles_root / ".zara" / "experts" / "nix" / "kb" / "expert.pl"
            ],
            "bash": [
                cls.dotfiles_root / ".zara" / "experts" / "bash" / "kb" / "expert.pl"
            ],
        }
        validate_language_source_contracts(cls.sources)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.host = ExpertHost(
            SwiplBackend(),
            state_root=Path(self.temporary.name) / "state",
        )
        registered = register_language_family(self.host, self.sources)
        self.assertEqual(registered, frozenset({"nix", "bash"}))
        self.composer = MetaExpertComposer(LanguageFamilyCompositionInvoker(self.host))
        self.fence = InvocationFence(
            workspace_id="workspace:nix-bash",
            workspace_generation=11,
            is_cancelled=lambda: False,
            is_current_generation=lambda workspace_id, generation: (
                workspace_id == "workspace:nix-bash" and generation == 11
            ),
        )

    def test_nix_and_bash_consume_one_canonical_shared_zero_model_budget(self) -> None:
        budget = SharedSymbolicBudget(
            max_invocations=2,
            max_depth=1,
            max_evidence=64,
            max_model_calls=0,
        )
        nix = self.composer.invoke(
            "zara:expert/nix",
            "inspect",
            {"source": "{ x = 1; }", "source_generation": "generation-11"},
            budget=budget,
            fence=self.fence,
        )
        bash = self.composer.invoke(
            "zara:expert/bash",
            "inspect",
            {
                "source": "printf '%s\\n' ok",
                "source_generation": "generation-11",
            },
            budget=budget,
            fence=self.fence,
        )

        self.assertEqual(nix.status, "succeeded")
        self.assertEqual(bash.status, "succeeded")
        self.assertEqual(budget.invocations_used, 2)
        self.assertGreaterEqual(budget.evidence_used, 0)
        self.assertEqual(budget.max_model_calls, 0)
        self.assertEqual(budget.model_calls_used, 0)

        with self.assertRaisesRegex(CompositionError, "invocation budget exceeded"):
            self.composer.invoke(
                "zara:expert/nix",
                "style.rules",
                {"source": "{ x = 1; }", "project_style": "style:project-v1"},
                budget=budget,
                fence=self.fence,
            )
        self.assertEqual(budget.invocations_used, 2)
        self.assertEqual(budget.model_calls_used, 0)

    def test_cancelled_fence_rejects_before_real_brain_dispatch(self) -> None:
        cancelled = InvocationFence(
            workspace_id="workspace:nix-bash",
            workspace_generation=11,
            is_cancelled=lambda: True,
            is_current_generation=lambda _workspace_id, _generation: True,
        )
        budget = SharedSymbolicBudget(max_invocations=2, max_model_calls=0)
        with self.assertRaisesRegex(CompositionError, "cancelled"):
            self.composer.invoke(
                "zara:expert/bash",
                "inspect",
                {
                    "source": "printf '%s\\n' should-not-run",
                    "source_generation": "generation-11",
                },
                budget=budget,
                fence=cancelled,
            )
        self.assertEqual(budget.invocations_used, 0)
        self.assertEqual(budget.model_calls_used, 0)


if __name__ == "__main__":
    unittest.main()
