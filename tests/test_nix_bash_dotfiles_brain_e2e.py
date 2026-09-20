import json
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
from zara_expert.domain import ExpertHost
from zara_expert.language_family import descriptors, register_language_family
from zara_expert.language_handler import make_language_expert_handler
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


def _prolog_fact(source: Path, goal: str) -> None:
    result = _run(
        "swipl",
        "-q",
        "-f",
        "none",
        "-s",
        str(source),
        "-g",
        f"(({goal})->halt(0);halt(1))",
    )
    if result.returncode != 0:
        raise AssertionError(
            f"canonical expert fact failed: {goal}\nstdout={result.stdout}\nstderr={result.stderr}"
        )


@unittest.skipUnless(DOTFILES_ROOT, "canonical Dotfiles checkout not provided")
class NixBashCanonicalBrainE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for canonical brain E2E")
        if shutil.which("nix-instantiate") is None:
            raise AssertionError("nix-instantiate is required for NixExpert parser E2E")

        checkout = _run("git", "rev-parse", "HEAD", cwd=cls.dotfiles_root)
        if checkout.returncode != 0:
            raise AssertionError(f"cannot resolve Dotfiles checkout: {checkout.stderr}")
        if checkout.stdout.strip() != EXPECTED_DOTFILES_COMMIT:
            raise AssertionError(
                "CI checkout must be the exact producer revision pinned by the adapters: "
                f"expected {EXPECTED_DOTFILES_COMMIT}, got {checkout.stdout.strip()}"
            )

        cls.nix_source = cls.dotfiles_root / ".zara" / "experts" / "nix" / "kb" / "expert.pl"
        cls.bash_source = cls.dotfiles_root / ".zara" / "experts" / "bash" / "kb" / "expert.pl"
        cls.adapter_contract = (
            cls.dotfiles_root / ".zara" / "experts" / "language" / "kb" / "adapter_contract.pl"
        )
        for source in (cls.nix_source, cls.bash_source, cls.adapter_contract):
            if not source.is_file():
                raise AssertionError(f"missing canonical expert source: {source}")

    def _load_lock(self, plugin: str) -> dict[str, object]:
        path = REPO_ROOT / "plugins" / plugin / "expert-source.lock.json"
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def test_source_locks_pin_the_executed_canonical_brains(self) -> None:
        expected = {
            "zara-nix-expert": ("zara:expert/nix", 286, 503, ".zara/experts/nix"),
            "zara-bash-expert": ("zara:expert/bash", 287, 502, ".zara/experts/bash"),
        }
        for plugin, (expert_id, issue, runtime_issue, source_path) in expected.items():
            with self.subTest(plugin=plugin):
                lock = self._load_lock(plugin)
                self.assertEqual(lock["schema_version"], 1)
                self.assertEqual(lock["expert_id"], expert_id)
                self.assertEqual(
                    lock["runtime_contract"],
                    {
                        "repository": "lost-rob0t/prolog-rlm",
                        "issue": runtime_issue,
                    },
                )
                canonical_source = lock["canonical_source"]
                self.assertIsInstance(canonical_source, dict)
                self.assertEqual(canonical_source["repository"], "lost-rob0t/dotfiles")
                self.assertEqual(canonical_source["path"], source_path)
                self.assertEqual(canonical_source["issue"], issue)
                self.assertEqual(canonical_source["producer_pr"], 300)
                self.assertEqual(canonical_source["commit"], EXPECTED_DOTFILES_COMMIT)

    def test_nix_brain_enforces_read_only_zero_model_contract(self) -> None:
        for goal in (
            "expert_id('zara:expert/nix')",
            "upstream_contract('lost-rob0t/prolog-rlm#503')",
            "provider_policy(disabled)",
            "max_model_calls(0)",
            "model_calls(0)",
            "inspection_build_policy(never)",
            "evaluation_policy(explicit_capability)",
            "build_policy(explicit_capability)",
            "parser_probe(nix_instantiate_parse,read_only)",
            "repair_verification(parse_then_eval_or_check)",
            "supports_semantic(style)",
            "supports_semantic(repair_verify)",
            "generation_current(7,7)",
        ):
            with self.subTest(goal=goal):
                _prolog_fact(self.nix_source, goal)

        parsed = _run(
            "nix-instantiate",
            "--parse",
            "--expr",
            'builtins.abort "must-not-evaluate"',
        )
        self.assertEqual(parsed.returncode, 0, parsed.stderr)

        rejected = _run("nix-instantiate", "--parse", "--expr", "{ broken = ; }")
        self.assertNotEqual(rejected.returncode, 0, "invalid Nix syntax must fail closed")

    def test_bash_brain_parses_without_executing_source(self) -> None:
        for goal in (
            "expert_id('zara:expert/bash')",
            "upstream_contract('lost-rob0t/prolog-rlm#502')",
            "provider_policy(disabled)",
            "max_model_calls(0)",
            "model_calls(0)",
            "inspection_policy(parse_only)",
            "source_execution_policy(never)",
            "parser_probe(bash_n,read_only)",
            "repair_verification(parse_and_bash_n)",
            "supports_semantic(style)",
            "supports_semantic(repair_verify)",
            "generation_current(7,7)",
        ):
            with self.subTest(goal=goal):
                _prolog_fact(self.bash_source, goal)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sentinel = root / "must-not-exist"
            source = root / "inspection.sh"
            source.write_text(f"touch {sentinel}\nprintf '%s\\n' ok\n", encoding="utf-8")
            checked = _run("bash", "-n", str(source))
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertFalse(sentinel.exists(), "read-only inspection must never execute source")

            broken = root / "broken.sh"
            broken.write_text("if true; then\n", encoding="utf-8")
            rejected = _run("bash", "-n", str(broken))
            self.assertNotEqual(rejected.returncode, 0, "invalid Bash syntax must fail closed")

    def test_real_brains_preflight_register_publish_and_invoke_through_zara_expert(self) -> None:
        sources = {
            "nix": [self.nix_source],
            "bash": [self.bash_source],
        }
        validate_language_source_contracts(sources)
        with tempfile.TemporaryDirectory() as temporary:
            host = ExpertHost(
                SwiplBackend(),
                state_root=Path(temporary) / "zara-expert-state",
            )
            registered = register_language_family(host, sources)
            self.assertEqual(registered, frozenset({"nix", "bash"}))

            published = {item["expert_id"]: item for item in descriptors(registered)}
            for expert_id in ("zara:expert/nix", "zara:expert/bash"):
                with self.subTest(expert_id=expert_id, phase="descriptor"):
                    descriptor = published[expert_id]
                    self.assertEqual(descriptor["availability"], "available")
                    self.assertEqual(descriptor["reasoning_kind"], "symbolic")
                    self.assertEqual(descriptor["resource_limits"]["max_model_calls"], 0)
                    self.assertEqual(descriptor["fallback_policy"], "fail_closed")

            cases = (
                ("zara:expert/nix", "{ x = 1; }"),
                ("zara:expert/bash", "printf '%s\\n' ok"),
            )
            for expert_id, source in cases:
                with self.subTest(expert_id=expert_id, phase="invoke"):
                    handler = make_language_expert_handler(host, expert_id)
                    outcome = handler(
                        expert_operation="inspect",
                        source=source,
                        source_generation="generation-7",
                    )
                    self.assertEqual(outcome["verdict"], "succeeded")
                    self.assertEqual(outcome["usage"], {"model_calls": 0})
                    self.assertEqual(outcome["effect_receipts"], [])
                    self.assertEqual(outcome["data"]["result"]["model_calls"], 0)
                    self.assertTrue(outcome["data"]["result"]["evidence"])

                    style = handler(
                        expert_operation="style.rules",
                        source=source,
                        project_style="style:project-v1",
                    )
                    self.assertEqual(style["usage"], {"model_calls": 0})
                    self.assertEqual(style["effect_receipts"], [])
                    self.assertTrue(style["data"]["result"]["evidence"])


if __name__ == "__main__":
    unittest.main()
