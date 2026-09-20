from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOTFILES_ROOT = os.environ.get("ZARA_DOTFILES_ROOT")
ZARA_CURRENT_CORE_ROOT = os.environ.get("ZARA_CURRENT_CORE_ROOT")
EXPECTED_DOTFILES_COMMIT = "fe8f7fa3c42803e0e505dcb6f7e4600d27649d9e"
EXPECTED_ZARA_CORE_COMMIT = "b9162dad35dfc17f8450e25503004222a813f9aa"
ZARA_EXPERT_LIB = REPO_ROOT / "plugins" / "zara-expert" / "lib"

if ZARA_CURRENT_CORE_ROOT:
    sys.path.insert(0, str(Path(ZARA_CURRENT_CORE_ROOT).resolve()))
sys.path.insert(0, str(ZARA_EXPERT_LIB))

from zara_expert.backend import SwiplBackend
from zara_expert.composition import CompositionError
from zara_expert.core_catalog import CoreExpertCatalogAdapter
from zara_expert.domain import ExpertHost
from zara_expert.language_family import descriptors, register_language_family
from zara_expert.language_handler import make_language_expert_handler
from zara_expert.language_source_contract import validate_language_source_contracts

if ZARA_CURRENT_CORE_ROOT:
    from zara.experts import (
        ExpertAmbiguityError,
        ExpertDescriptor,
        ExpertLimits,
        ExpertRegistry,
        ExpertVerdict,
    )


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
        raise AssertionError(
            f"{label} checkout must be exact: expected {expected}, got {actual}"
        )


@unittest.skipUnless(
    DOTFILES_ROOT and ZARA_CURRENT_CORE_ROOT,
    "exact Dotfiles and current Zara Core checkouts not provided",
)
class NixBashCoreCatalogE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        cls.zara_core_root = Path(ZARA_CURRENT_CORE_ROOT).resolve()
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for Core catalog E2E")
        _checkout_head(cls.dotfiles_root, EXPECTED_DOTFILES_COMMIT, "Dotfiles producer")
        _checkout_head(cls.zara_core_root, EXPECTED_ZARA_CORE_COMMIT, "Zara Core")
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
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.host = ExpertHost(
            SwiplBackend(),
            state_root=Path(temporary.name) / "zara-expert-state",
        )
        registered = register_language_family(self.host, self.sources)
        self.assertEqual(registered, frozenset({"nix", "bash"}))
        published = {item["expert_id"]: item for item in descriptors(registered)}

        self.registry = ExpertRegistry(engines=("swipl",))
        for expert_id in ("zara:expert/nix", "zara:expert/bash"):
            descriptor = ExpertDescriptor.from_wire(published[expert_id])
            self.registry.register(
                descriptor,
                make_language_expert_handler(self.host, expert_id),
            )
        self.catalog = CoreExpertCatalogAdapter(
            self.registry,
            principal="user:nix-bash-core-catalog",
        )

    def _select_and_inspect(
        self,
        *,
        goal: str,
        expected_expert_id: str,
        source: str,
    ) -> None:
        selection = self.catalog.select(goal)
        self.assertEqual(selection.expert_id, expected_expert_id)
        self.assertEqual(selection.registry_generation, self.registry.generation)
        self.assertEqual(selection.runtime_generation, self.registry.runtime_generation)
        self.assertEqual(selection.descriptor["registry_generation"], 0)
        self.assertEqual(selection.descriptor["resource_limits"]["max_model_calls"], 0)
        self.assertIn("canonical Zara ExpertRegistry selected", selection.explanation)

        handle, _ = self.registry.activate(
            "user:nix-bash-core-catalog",
            "workspace:nix-bash-core-catalog",
            selection.expert_id,
            expected_registry_generation=selection.registry_generation,
            expected_runtime_generation=selection.runtime_generation,
        )
        result = self.registry.invoke(
            handle,
            "inspect",
            {
                "source": source,
                "source_generation": "generation:core-catalog",
            },
            limits=ExpertLimits(max_model_calls=0),
            request_id=f"req:core-catalog:{expected_expert_id.rsplit('/', 1)[-1]}",
        )
        self.assertIs(result.verdict, ExpertVerdict.SUCCEEDED)
        self.assertEqual(result.usage, {"model_calls": 0})
        self.assertEqual(result.effect_receipts, ())

    def test_catalog_selects_real_nix_and_bash_brains_then_core_invokes_them(self) -> None:
        self._select_and_inspect(
            goal="inspect this nix flake",
            expected_expert_id="zara:expert/nix",
            source="{ x = 1; }",
        )
        self._select_and_inspect(
            goal="inspect this bash script",
            expected_expert_id="zara:expert/bash",
            source="printf '%s\\n' ok",
        )

    def test_catalog_missing_and_ambiguous_requests_fail_closed(self) -> None:
        with self.assertRaisesRegex(CompositionError, "no symbolic match"):
            self.catalog.select("request with no registered language keyword")

        with self.assertRaises(ExpertAmbiguityError):
            self.catalog.select("nix bash")


if __name__ == "__main__":
    unittest.main()
