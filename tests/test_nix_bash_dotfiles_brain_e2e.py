import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOTFILES_ROOT = os.environ.get("ZARA_DOTFILES_ROOT")
EXPECTED_DOTFILES_COMMIT = "5c8d8670a18c97cebc33af8be85549a8fcb6bf02"


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
        for source in (cls.nix_source, cls.bash_source):
            if not source.is_file():
                raise AssertionError(f"missing canonical expert source: {source}")

    def _load_lock(self, plugin: str) -> dict[str, object]:
        path = REPO_ROOT / "plugins" / plugin / "expert-source.lock.json"
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def test_source_locks_pin_the_executed_canonical_brains(self) -> None:
        expected = {
            "zara-nix-expert": ("zara:expert/nix", 503, ".zara/experts/nix"),
            "zara-bash-expert": ("zara:expert/bash", 502, ".zara/experts/bash"),
        }
        for plugin, (expert_id, runtime_issue, source_path) in expected.items():
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


if __name__ == "__main__":
    unittest.main()
