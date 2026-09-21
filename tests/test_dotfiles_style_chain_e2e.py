import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOTFILES_ROOT = os.environ.get("ZARA_DOTFILES_CHAIN_ROOT")
ZARA_CORE_ROOT = os.environ.get("ZARA_CORE_CURRENT_ROOT")
PROLOG_RLM_ROOT = os.environ.get("PROLOG_RLM_ROOT")
EXPECTED_DOTFILES_COMMIT = "4fc75059cd0eb242559e0ec2786e7d78875a310d"
EXPECTED_ZARA_CORE_COMMIT = "4f30f9f18c06ba3a5daf11122e0e2a8af30f7095"
EXPECTED_PROLOG_RLM_COMMIT = "4715b5ee53d0e7a26c55705ea85c0d16c3916504"
ZARA_EXPERT_LIB = REPO_ROOT / "plugins" / "zara-expert" / "lib"

if ZARA_CORE_ROOT:
    sys.path.insert(0, str(Path(ZARA_CORE_ROOT).resolve()))
sys.path.insert(0, str(ZARA_EXPERT_LIB))

from zara_expert import DotfilesStyleLanguageChainInvoker
from zara_expert.backend import SwiplBackend
from zara_expert.catalog_composition import CoreCatalogSelectedChildInvoker
from zara_expert.composition import InvocationFence, MetaExpertComposer, SharedSymbolicBudget
from zara_expert.core_catalog import CoreExpertCatalogAdapter
from zara_expert.domain import ExpertHost
from zara_expert.dotfiles_composition import CoreDotfilesCompositionInvoker
from zara_expert.dotfiles_family import descriptor as dotfiles_descriptor
from zara_expert.dotfiles_family import register_dotfiles_expert
from zara_expert.dotfiles_handler import make_dotfiles_expert_handler
from zara_expert.dotfiles_style_expert import (
    STYLE_EXPERT_ID,
    DotfilesStyleCompositionInvoker,
    register_dotfiles_style_expert,
)
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
    DOTFILES_ROOT and ZARA_CORE_ROOT and PROLOG_RLM_ROOT,
    "exact Dotfiles, Zara Core, and Prolog-RLM checkouts not provided",
)
class DotfilesStyleChainE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        cls.zara_core_root = Path(ZARA_CORE_ROOT).resolve()
        cls.prolog_rlm_root = Path(PROLOG_RLM_ROOT).resolve()
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for Dotfiles style-chain E2E")
        _checkout_head(cls.dotfiles_root, EXPECTED_DOTFILES_COMMIT, "Dotfiles pending producer")
        _checkout_head(cls.zara_core_root, EXPECTED_ZARA_CORE_COMMIT, "current Zara Core")
        _checkout_head(cls.prolog_rlm_root, EXPECTED_PROLOG_RLM_COMMIT, "Prolog-RLM")

        cls.dotfiles_source = (
            cls.dotfiles_root / ".zara" / "experts" / "dotfiles" / "kb" / "expert.pl"
        )
        cls.style_source = (
            cls.dotfiles_root / ".zara" / "experts" / "style" / "kb" / "expert.pl"
        )
        cls.language_sources = {
            "nix": [cls.dotfiles_root / ".zara" / "experts" / "nix" / "kb" / "expert.pl"],
            "bash": [cls.dotfiles_root / ".zara" / "experts" / "bash" / "kb" / "expert.pl"],
        }
        cls.style_runtime = cls.prolog_rlm_root / "prolog" / "rlm_style_overlay.pl"
        for path in (cls.dotfiles_source, cls.style_source, cls.style_runtime):
            if not path.is_file():
                raise AssertionError(f"missing canonical symbolic source: {path}")
        validate_language_source_contracts(cls.language_sources)

    @classmethod
    def _resolve_style(cls, rules, context):
        payload = json.dumps({"rules": list(rules), "context": dict(context)}, sort_keys=True)
        goal = (
            "use_module(library(http/json)),"
            "json_read_dict(current_input,Input,[value_string_as(atom)]),"
            "get_dict(rules,Input,Rules),get_dict(context,Input,Context),"
            "rlm_style_overlay:style_overlay_resolve(Rules,Context,Result),"
            "json_write_dict(current_output,Result,[width(0)]),nl"
        )
        result = subprocess.run(
            [
                "swipl",
                "-q",
                "-s",
                str(cls.style_runtime),
                "-g",
                goal,
                "-t",
                "halt",
            ],
            input=payload,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            raise AssertionError(f"canonical Prolog-RLM style resolver failed: {result.stderr}")
        decoded = json.loads(result.stdout)
        if not isinstance(decoded, dict):
            raise AssertionError("canonical Prolog-RLM style resolver returned non-object")
        return decoded

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
        register_dotfiles_style_expert(self.host, self.style_source)

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
        workspace = "workspace:dotfiles-style-chain-e2e"
        for expert_id in ("zara:expert/dotfiles", "zara:expert/nix", "zara:expert/bash"):
            handle, receipt = self.registry.activate(
                f"dotfiles-style-chain:{expert_id.rsplit('/', 1)[-1]}",
                workspace,
                expert_id,
                expected_registry_generation=self.registry.generation,
                expected_runtime_generation=self.registry.runtime_generation,
            )
            self.assertEqual(receipt["state"], "active")
            self.handles[expert_id] = handle

        language_invoker = CoreLanguageFamilyCompositionInvoker(
            self.registry,
            activation_for=lambda expert_id, _fence: self.handles[expert_id],
            limits_factory=ExpertLimits,
        )
        catalog_language_invoker = CoreCatalogSelectedChildInvoker(
            CoreExpertCatalogAdapter(
                self.registry,
                principal="user:dotfiles-style-chain-e2e",
            ),
            language_invoker,
            goal_for=lambda expert_id, operation, _input: {
                "zara:expert/nix": f"{operation} nix nixos flake",
                "zara:expert/bash": f"{operation} bash shell sh",
            }[expert_id],
        )
        style_invoker = DotfilesStyleCompositionInvoker(
            self.host,
            resolver=self._resolve_style,
        )
        chain_invoker = DotfilesStyleLanguageChainInvoker(
            catalog_language_invoker,
            style_invoker,
        )
        self.invoker = CoreDotfilesCompositionInvoker(
            self.registry,
            activation_for=lambda expert_id, _fence: self.handles[expert_id],
            limits_factory=ExpertLimits,
            child_invoker=chain_invoker,
        )
        self.composer = MetaExpertComposer(self.invoker)
        self.fence = InvocationFence(
            workspace_id=workspace,
            workspace_generation=23,
            is_cancelled=lambda: False,
            is_current_generation=lambda workspace_id, generation: (
                workspace_id == workspace and generation == 23
            ),
        )

    def test_dotfiles_to_language_to_style_uses_one_zero_model_budget(self) -> None:
        cases = (
            ("flake.nix", "{ x = 1; }", "nix", "zara:expert/nix"),
            ("bin/deploy.sh", "printf '%s\\n' ok", "bash", "zara:expert/bash"),
        )
        for path, source, language, language_expert_id in cases:
            with self.subTest(language=language):
                budget = SharedSymbolicBudget(
                    max_invocations=3,
                    max_depth=2,
                    max_evidence=128,
                    max_model_calls=0,
                )
                tree = self.composer.invoke(
                    "zara:expert/dotfiles",
                    "inspect",
                    {
                        "path": path,
                        "source": source,
                        "source_generation": "generation-23",
                    },
                    budget=budget,
                    fence=self.fence,
                )

                self.assertEqual(tree.status, "succeeded")
                self.assertEqual(tree.data["specialist_expert_id"], language_expert_id)
                self.assertEqual(len(tree.children), 1)
                language_node = tree.children[0]
                self.assertEqual(language_node.expert_id, language_expert_id)
                self.assertEqual(language_node.status, "succeeded")
                self.assertIn("canonical Zara ExpertRegistry selected", language_node.explanation)
                self.assertEqual(len(language_node.children), 1)

                style_node = language_node.children[0]
                self.assertEqual(style_node.expert_id, STYLE_EXPERT_ID)
                self.assertEqual(style_node.operation, "resolve")
                self.assertEqual(style_node.status, "succeeded")
                self.assertEqual(style_node.data["language"], language)
                self.assertTrue(style_node.data["rules"])
                self.assertTrue(style_node.data["effective"])
                self.assertIn("style-expert:provider_policy=disabled", style_node.evidence)
                self.assertIn("style-expert:max_model_calls=0", style_node.evidence)
                self.assertIn("style-expert:model_calls=0", style_node.evidence)
                self.assertTrue(any(item.startswith("style:") for item in style_node.evidence))
                self.assertIn("style_overlay_resolve/3", style_node.explanation)

                expected_evidence = (
                    len(tree.evidence)
                    + len(language_node.evidence)
                    + len(style_node.evidence)
                )
                self.assertEqual(budget.invocations_used, 3)
                self.assertEqual(budget.evidence_used, expected_evidence)
                self.assertEqual(budget.max_model_calls, 0)
                self.assertEqual(budget.model_calls_used, 0)


if __name__ == "__main__":
    unittest.main()
