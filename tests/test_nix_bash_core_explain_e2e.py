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
EXPECTED_DOTFILES_COMMIT = "1b93e01f3482e49a853f651eb28c21eb1d9cad0e"
EXPECTED_ZARA_CORE_COMMIT = "fded1099e82f315b069676d1aadd66fe96aebccc"
ZARA_EXPERT_LIB = REPO_ROOT / "plugins" / "zara-expert" / "lib"

if ZARA_CORE_ROOT:
    sys.path.insert(0, str(Path(ZARA_CORE_ROOT).resolve()))
sys.path.insert(0, str(ZARA_EXPERT_LIB))

from zara_expert.backend import SwiplBackend
from zara_expert.domain import ExpertHost
from zara_expert.language_family import descriptors, register_language_family
from zara_expert.language_handler import make_language_expert_handler
from zara_expert.language_source_contract import validate_language_source_contracts

if ZARA_CORE_ROOT:
    from zara.experts import ExpertDescriptor, ExpertLimits, ExpertRegistry, ExpertVerdict


def _run(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _assert_exact_checkout(root: Path, expected: str, label: str) -> None:
    result = _run("git", "rev-parse", "HEAD", cwd=root)
    if result.returncode != 0:
        raise AssertionError(f"cannot resolve {label} checkout: {result.stderr}")
    actual = result.stdout.strip()
    if actual != expected:
        raise AssertionError(
            f"{label} checkout must be exact: expected {expected}, got {actual}"
        )


@unittest.skipUnless(
    DOTFILES_ROOT and ZARA_CORE_ROOT,
    "exact Dotfiles and Zara Core checkouts not provided",
)
class NixBashCoreExplainE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for Nix/Bash explain E2E")
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        cls.zara_core_root = Path(ZARA_CORE_ROOT).resolve()
        _assert_exact_checkout(
            cls.dotfiles_root,
            EXPECTED_DOTFILES_COMMIT,
            "Dotfiles producer",
        )
        _assert_exact_checkout(
            cls.zara_core_root,
            EXPECTED_ZARA_CORE_COMMIT,
            "Zara Core",
        )

        cls.sources = {
            "nix": [
                cls.dotfiles_root
                / ".zara"
                / "experts"
                / "nix"
                / "kb"
                / "expert.pl"
            ],
            "bash": [
                cls.dotfiles_root
                / ".zara"
                / "experts"
                / "bash"
                / "kb"
                / "expert.pl"
            ],
        }
        validate_language_source_contracts(cls.sources)
        for paths in cls.sources.values():
            for source in paths:
                if not source.is_file():
                    raise AssertionError(f"missing canonical expert source: {source}")

    def test_real_brains_explain_prior_core_decisions_with_zero_model_usage(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        host = ExpertHost(
            SwiplBackend(),
            state_root=Path(temporary.name) / "zara-expert-state",
        )
        registered = register_language_family(host, self.sources)
        self.assertEqual(registered, frozenset({"nix", "bash"}))
        published = {item["expert_id"]: item for item in descriptors(registered)}

        registry = ExpertRegistry(engines=("swipl",))
        for expert_id in ("zara:expert/nix", "zara:expert/bash"):
            descriptor = ExpertDescriptor.from_wire(published[expert_id])
            self.assertEqual(descriptor.resource_limits.max_model_calls, 0)
            registration = registry.register(
                descriptor,
                make_language_expert_handler(host, expert_id),
            )
            self.assertEqual(registration["expert_id"], expert_id)

        cases = {
            "zara:expert/nix": "{ x = 1; }",
            "zara:expert/bash": "printf '%s\\n' ok",
        }
        for expert_id, source in cases.items():
            with self.subTest(expert_id=expert_id):
                short_name = expert_id.rsplit("/", 1)[-1]
                handle, receipt = registry.activate(
                    f"nix-bash-explain:{short_name}",
                    "workspace:nix-bash-explain",
                    expert_id,
                    expected_registry_generation=registry.generation,
                    expected_runtime_generation=registry.runtime_generation,
                )
                self.assertEqual(receipt["state"], "active")

                inspect_request_id = f"req:{short_name}:inspect:23"
                inspected = registry.invoke(
                    handle,
                    "inspect",
                    {
                        "source": source,
                        "source_generation": "generation-23",
                    },
                    limits=ExpertLimits(max_model_calls=0),
                    request_id=inspect_request_id,
                )
                self.assertIs(inspected.verdict, ExpertVerdict.SUCCEEDED)
                self.assertEqual(inspected.usage, {"model_calls": 0})
                self.assertEqual(inspected.effect_receipts, ())

                explained = registry.invoke(
                    handle,
                    "explain",
                    {
                        "decision_ref": f"decision:{inspect_request_id}",
                        "source_generation": "generation-23",
                    },
                    limits=ExpertLimits(max_model_calls=0),
                    request_id=f"req:{short_name}:why:23",
                )
                self.assertIs(explained.verdict, ExpertVerdict.SUCCEEDED)
                self.assertEqual(explained.usage, {"model_calls": 0})
                self.assertEqual(explained.effect_receipts, ())
                self.assertEqual(
                    explained.resolved_registry_generation,
                    registry.generation,
                )
                self.assertEqual(
                    explained.resolved_runtime_generation,
                    registry.runtime_generation,
                )

                brain_result = explained.data["result"]
                self.assertEqual(brain_result["expert_id"], expert_id)
                self.assertEqual(brain_result["operation"], "explain")
                self.assertEqual(brain_result["model_calls"], 0)
                self.assertEqual(brain_result["effect_receipts"], [])
                self.assertTrue(brain_result["evidence"])
                self.assertTrue(
                    any(
                        "provider_policy(disabled)" in item
                        for item in brain_result["evidence"]
                    )
                )
                self.assertTrue(
                    any("model_calls(0)" in item for item in brain_result["evidence"])
                )
                self.assertTrue(
                    any(
                        f"decision_ref(decision:{inspect_request_id})" in item
                        for item in brain_result["evidence"]
                    )
                )


if __name__ == "__main__":
    unittest.main()
