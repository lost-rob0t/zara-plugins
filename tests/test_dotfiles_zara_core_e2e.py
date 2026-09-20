import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOTFILES_ROOT = os.environ.get("ZARA_DOTFILES_ROOT")
ZARA_CORE_ROOT = os.environ.get("ZARA_CORE_ROOT")
EXPECTED_DOTFILES_COMMIT = "1c825e84a4ca2eaee6fa9a7db8c251b256d991c9"
EXPECTED_ZARA_CORE_COMMIT = "fded1099e82f315b069676d1aadd66fe96aebccc"
ZARA_EXPERT_LIB = REPO_ROOT / "plugins" / "zara-expert" / "lib"

if ZARA_CORE_ROOT:
    sys.path.insert(0, str(Path(ZARA_CORE_ROOT).resolve()))
sys.path.insert(0, str(ZARA_EXPERT_LIB))

from zara_expert.backend import SwiplBackend
from zara_expert.composition import InvocationFence, MetaExpertComposer, SharedSymbolicBudget
from zara_expert.domain import ExpertHost
from zara_expert.dotfiles_composition import CoreDotfilesCompositionInvoker
from zara_expert.dotfiles_family import descriptor as dotfiles_descriptor
from zara_expert.dotfiles_family import register_dotfiles_expert
from zara_expert.dotfiles_handler import make_dotfiles_expert_handler
from zara_expert.language_composition import CoreLanguageFamilyCompositionInvoker
from zara_expert.language_family import descriptors, register_language_family
from zara_expert.language_handler import make_language_expert_handler
from zara_expert.language_source_contract import validate_language_source_contracts

if ZARA_CORE_ROOT:
    from zara.experts import ExpertDescriptor, ExpertLimits, ExpertRegistry


def _run(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _checkout_head(root: Path, expected: str, label: str) -> None:
    result = _run("git", "rev-parse", "HEAD", cwd=root)
    if result.returncode != 0:
        raise AssertionError(f"cannot resolve {label} checkout: {result.stderr}")
    actual = result.stdout.strip()
    if actual != expected:
        raise AssertionError(f"{label} checkout must be exact: expected {expected}, got {actual}")


@unittest.skipUnless(
    DOTFILES_ROOT and ZARA_CORE_ROOT,
    "exact Dotfiles and Zara Core checkouts not provided",
)
class DotfilesZaraCoreE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        cls.zara_core_root = Path(ZARA_CORE_ROOT).resolve()
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for DotfilesExpert E2E")
        _checkout_head(cls.dotfiles_root, EXPECTED_DOTFILES_COMMIT, "Dotfiles producer")
        _checkout_head(cls.zara_core_root, EXPECTED_ZARA_CORE_COMMIT, "Zara Core")

        cls.dotfiles_source = (
            cls.dotfiles_root / ".zara" / "experts" / "dotfiles" / "kb" / "expert.pl"
        )
        cls.language_sources = {
            "nix": [cls.dotfiles_root / ".zara" / "experts" / "nix" / "kb" / "expert.pl"],
            "bash": [cls.dotfiles_root / ".zara" / "experts" / "bash" / "kb" / "expert.pl"],
        }
        if not cls.dotfiles_source.is_file():
            raise AssertionError(f"missing canonical DotfilesExpert source: {cls.dotfiles_source}")
        validate_language_source_contracts(cls.language_sources)

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.host = ExpertHost(
            SwiplBackend(),
            state_root=Path(temporary.name) / "zara-expert-state",
        )
        register_dotfiles_expert(self.host, [self.dotfiles_source])
        registered = register_language_family(self.host, self.language_sources)
        self.assertEqual(registered, frozenset({"nix", "bash"}))

        language_descriptors = {item["expert_id"]: item for item in descriptors(registered)}
        self.registry = ExpertRegistry(engines=("swipl",))
        self.registry.register(
            ExpertDescriptor.from_wire(dotfiles_descriptor(available=True)),
            make_dotfiles_expert_handler(self.host),
        )
        for expert_id in ("zara:expert/nix", "zara:expert/bash"):
            self.registry.register(
                ExpertDescriptor.from_wire(language_descriptors[expert_id]),
                make_language_expert_handler(self.host, expert_id),
            )

        self.handles = {}
        for expert_id in ("zara:expert/dotfiles", "zara:expert/nix", "zara:expert/bash"):
            handle, receipt = self.registry.activate(
                f"dotfiles-core-e2e:{expert_id.rsplit('/', 1)[-1]}",
                "workspace:dotfiles-core-e2e",
                expert_id,
                expected_registry_generation=self.registry.generation,
                expected_runtime_generation=self.registry.runtime_generation,
            )
            self.assertEqual(receipt["state"], "active")
            self.handles[expert_id] = handle

        child_invoker = CoreLanguageFamilyCompositionInvoker(
            self.registry,
            activation_for=lambda expert_id, _fence: self.handles[expert_id],
            limits_factory=ExpertLimits,
        )
        self.invoker = CoreDotfilesCompositionInvoker(
            self.registry,
            activation_for=lambda expert_id, _fence: self.handles[expert_id],
            limits_factory=ExpertLimits,
            child_invoker=child_invoker,
        )
        self.composer = MetaExpertComposer(self.invoker)
        self.fence = InvocationFence(
            workspace_id="workspace:dotfiles-core-e2e",
            workspace_generation=17,
            is_cancelled=lambda: False,
            is_current_generation=lambda workspace_id, generation: (
                workspace_id == "workspace:dotfiles-core-e2e" and generation == 17
            ),
        )

    def test_real_dotfiles_root_delegates_to_real_core_nix_and_bash(self) -> None:
        cases = (
            ("flake.nix", "{ x = 1; }", "nix", "zara:expert/nix"),
            ("bin/deploy.sh", "printf '%s\\n' ok", "bash", "zara:expert/bash"),
        )
        for path, source, language, child_id in cases:
            with self.subTest(path=path):
                budget = SharedSymbolicBudget(
                    max_invocations=2,
                    max_depth=1,
                    max_evidence=64,
                    max_model_calls=0,
                )
                tree = self.composer.invoke(
                    "zara:expert/dotfiles",
                    "inspect",
                    {
                        "path": path,
                        "source": source,
                        "source_generation": "generation-17",
                    },
                    budget=budget,
                    fence=self.fence,
                )
                self.assertEqual(tree.status, "succeeded")
                self.assertEqual(tree.data["language"], language)
                self.assertEqual(tree.data["specialist_expert_id"], child_id)
                self.assertEqual(len(tree.children), 1)
                child = tree.children[0]
                self.assertEqual(child.expert_id, child_id)
                self.assertEqual(child.status, "succeeded")
                self.assertIn("registered", child.reason)
                self.assertIn("ZARA-EXPERT/1", child.explanation)
                self.assertEqual(budget.invocations_used, 2)
                self.assertEqual(budget.max_model_calls, 0)
                self.assertEqual(budget.model_calls_used, 0)

    def test_real_ownership_query_reuses_durable_dotfiles_kb(self) -> None:
        budget = SharedSymbolicBudget(max_invocations=1, max_model_calls=0)
        tree = self.composer.invoke(
            "zara:expert/dotfiles",
            "ownership",
            {"path": "/.config/systemd/user/zara-server.service"},
            budget=budget,
            fence=self.fence,
        )
        self.assertEqual(tree.status, "succeeded")
        self.assertEqual(tree.data["owner"], "home_manager")
        self.assertEqual(tree.children, ())
        self.assertEqual(budget.invocations_used, 1)
        self.assertEqual(budget.model_calls_used, 0)

    def test_unknown_path_stays_symbolic_unknown_without_child_fallback(self) -> None:
        budget = SharedSymbolicBudget(max_invocations=2, max_model_calls=0)
        tree = self.composer.invoke(
            "zara:expert/dotfiles",
            "inspect",
            {
                "path": "README.md",
                "source": "plain text",
                "source_generation": "generation-17",
            },
            budget=budget,
            fence=self.fence,
        )
        self.assertEqual(tree.status, "unknown")
        self.assertEqual(tree.data["reason"], "unsupported-path")
        self.assertEqual(tree.children, ())
        self.assertEqual(budget.invocations_used, 1)
        self.assertEqual(budget.model_calls_used, 0)

    def test_effect_request_is_blocked_before_any_write(self) -> None:
        budget = SharedSymbolicBudget(max_invocations=1, max_model_calls=0)
        tree = self.composer.invoke(
            "zara:expert/dotfiles",
            "repair.apply",
            {
                "repair": {"kind": "preview-only"},
                "expected_preimage": "before",
                "source_generation": "generation-17",
            },
            budget=budget,
            fence=self.fence,
        )
        self.assertEqual(tree.status, "blocked")
        self.assertEqual(tree.data["reason"], "canonical-typed-edit-required")
        self.assertEqual(tree.children, ())
        self.assertEqual(budget.model_calls_used, 0)


if __name__ == "__main__":
    unittest.main()
