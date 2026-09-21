import hashlib
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
PROVIDER_ENV = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "ZAI_API_KEY",
)

sys.path.insert(0, str(ZARA_EXPERT_LIB))

from zara_expert.backend import SwiplBackend
from zara_expert.domain import ExpertHost
from zara_expert.language_family import register_language_family
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


class _CanonicalReceiptFixture:
    """Read-only stand-in for Zara's already-verified outcome lookup authority."""

    def __init__(self) -> None:
        self.requests: list[dict[str, str]] = []

    def __call__(
        self,
        *,
        expert_id: str,
        source_generation: str,
        candidate_sha256: str,
        required_postcondition: str,
    ) -> dict[str, object]:
        request = {
            "expert_id": expert_id,
            "source_generation": source_generation,
            "candidate_sha256": candidate_sha256,
            "required_postcondition": required_postcondition,
        }
        self.requests.append(request)
        suffix = expert_id.rsplit("/", 1)[-1]
        return {
            **request,
            "receipt_ref": (
                "zara.verified-outcome/v1:outcome:postcondition/"
                f"nix-bash-e2e-{suffix}"
            ),
            "verified": True,
            "fresh": True,
        }


@unittest.skipUnless(DOTFILES_ROOT, "canonical Dotfiles checkout not provided")
class NixBashRepairVerifyE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for Nix/Bash repair.verify E2E")

        checkout = _run("git", "rev-parse", "HEAD", cwd=cls.dotfiles_root)
        if checkout.returncode != 0:
            raise AssertionError(f"cannot resolve Dotfiles checkout: {checkout.stderr}")
        if checkout.stdout.strip() != EXPECTED_DOTFILES_COMMIT:
            raise AssertionError(
                "repair.verify E2E must execute the exact package-pinned Dotfiles producer: "
                f"expected {EXPECTED_DOTFILES_COMMIT}, got {checkout.stdout.strip()}"
            )

        cls.sources = {
            "nix": [
                cls.dotfiles_root / ".zara" / "experts" / "nix" / "kb" / "expert.pl"
            ],
            "bash": [
                cls.dotfiles_root / ".zara" / "experts" / "bash" / "kb" / "expert.pl"
            ],
        }
        for expert_sources in cls.sources.values():
            for source in expert_sources:
                if not source.is_file():
                    raise AssertionError(f"missing canonical expert source: {source}")
        validate_language_source_contracts(cls.sources)

    def setUp(self) -> None:
        for name in PROVIDER_ENV:
            self.assertNotIn(name, os.environ, f"provider credential leaked into pure-symbolic E2E: {name}")

    def test_real_nix_and_bash_repair_verify_require_fresh_postcondition(self) -> None:
        cases = (
            (
                "zara:expert/nix",
                "{ answer = 41; }",
                "{ answer = 42; }",
                "parse_then_eval_or_check",
            ),
            (
                "zara:expert/bash",
                "printf '%s\\n' old",
                "printf '%s\\n' fixed",
                "parse_and_bash_n",
            ),
        )

        with tempfile.TemporaryDirectory() as temporary:
            host = ExpertHost(
                SwiplBackend(),
                state_root=Path(temporary) / "zara-expert-state",
            )
            registered = register_language_family(host, self.sources)
            self.assertEqual(registered, frozenset({"nix", "bash"}))

            for expert_id, original, candidate, required_postcondition in cases:
                with self.subTest(expert_id=expert_id):
                    handler = make_language_expert_handler(host, expert_id)
                    outcome = handler(
                        expert_operation="repair.verify",
                        original_source=original,
                        candidate_source=candidate,
                        source_generation="generation-repair-verify-e2e",
                    )

                    self.assertEqual(outcome["verdict"], "blocked")
                    self.assertEqual(outcome["usage"], {"model_calls": 0})
                    self.assertEqual(outcome["effect_receipts"], [])

                    result = outcome["data"]["result"]
                    self.assertEqual(result["model_calls"], 0)
                    self.assertEqual(result["effect_receipts"], [])
                    evidence = "\n".join(result["evidence"])
                    self.assertIn("verified(false)", evidence)
                    self.assertIn(
                        f"fresh_postcondition_required({required_postcondition})",
                        evidence,
                    )
                    self.assertIn(
                        f"required_postcondition({required_postcondition})",
                        evidence,
                    )

    def test_real_brains_accept_only_host_supplied_bound_verified_outcome(self) -> None:
        cases = (
            (
                "zara:expert/nix",
                "{ answer = 41; }",
                "{ answer = 42; }",
                "parse_then_eval_or_check",
            ),
            (
                "zara:expert/bash",
                "printf '%s\\n' old",
                "printf '%s\\n' fixed",
                "parse_and_bash_n",
            ),
        )
        generation = "generation-repair-verify-receipt-e2e"

        with tempfile.TemporaryDirectory() as temporary:
            host = ExpertHost(
                SwiplBackend(),
                state_root=Path(temporary) / "zara-expert-state",
            )
            register_language_family(host, self.sources)

            for expert_id, original, candidate, required_postcondition in cases:
                with self.subTest(expert_id=expert_id):
                    resolver = _CanonicalReceiptFixture()
                    outcome = make_language_expert_handler(
                        host,
                        expert_id,
                        verified_outcome_resolver=resolver,
                    )(
                        expert_operation="repair.verify",
                        original_source=original,
                        candidate_source=candidate,
                        source_generation=generation,
                    )

                    self.assertEqual(outcome["verdict"], "succeeded")
                    self.assertEqual(outcome["usage"], {"model_calls": 0})
                    self.assertEqual(outcome["effect_receipts"], [])
                    self.assertTrue(outcome["data"]["verified"])
                    receipt_ref = outcome["data"]["verified_outcome_ref"]
                    self.assertTrue(
                        receipt_ref.startswith(
                            "zara.verified-outcome/v1:outcome:postcondition/"
                        )
                    )
                    self.assertIn(receipt_ref, outcome["evidence_refs"])

                    result = outcome["data"]["result"]
                    self.assertEqual(result["model_calls"], 0)
                    self.assertEqual(result["effect_receipts"], [])
                    self.assertIn("verified(false)", "\n".join(result["evidence"]))
                    self.assertEqual(
                        resolver.requests,
                        [
                            {
                                "expert_id": expert_id,
                                "source_generation": generation,
                                "candidate_sha256": hashlib.sha256(
                                    candidate.encode("utf-8")
                                ).hexdigest(),
                                "required_postcondition": required_postcondition,
                            }
                        ],
                    )

    def test_real_nix_and_bash_repair_apply_cannot_escape_typed_effect_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            host = ExpertHost(
                SwiplBackend(),
                state_root=Path(temporary) / "zara-expert-state",
            )
            register_language_family(host, self.sources)

            for expert_id in ("zara:expert/nix", "zara:expert/bash"):
                with self.subTest(expert_id=expert_id):
                    outcome = make_language_expert_handler(host, expert_id)(
                        expert_operation="repair.apply",
                        repair={"kind": "replace", "replacement": "inert"},
                        expected_preimage="original",
                        source_generation="generation-repair-apply-e2e",
                    )
                    self.assertEqual(outcome["verdict"], "blocked")
                    self.assertEqual(
                        outcome["data"]["reason"],
                        "canonical-typed-edit-required",
                    )
                    self.assertEqual(outcome["usage"], {"model_calls": 0})
                    self.assertEqual(outcome["effect_receipts"], [])


if __name__ == "__main__":
    unittest.main()
