import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import PrologRLMBridge
from zara_coding.repository_evidence import build_repository_evidence
from zara_coding.spec_verify import verify_repository_spec


class RepositoryBranchAssertionTests(unittest.TestCase):
    def test_repository_evidence_includes_exact_observed_branch(self):
        evidence = build_repository_evidence(
            {
                "root": "/srv/demo",
                "head": "a" * 40,
                "branch": "feature/verify",
                "dirty": False,
            }
        )
        self.assertEqual(
            evidence["values"]["repository_branch"],
            {"root": "/srv/demo", "branch": "feature/verify"},
        )

    def test_repository_evidence_rejects_missing_or_empty_branch(self):
        with self.assertRaisesRegex(ValueError, "branch"):
            build_repository_evidence(
                {"root": "/srv/demo", "head": "a" * 40, "dirty": False}
            )
        with self.assertRaisesRegex(ValueError, "branch"):
            build_repository_evidence(
                {
                    "root": "/srv/demo",
                    "head": "a" * 40,
                    "branch": "",
                    "dirty": False,
                }
            )

    def test_verify_payload_carries_branch_to_prolog(self):
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout="ok(verification_report{status:passed})\n",
                stderr="",
            )

        bridge = PrologRLMBridge(Path("/srv/prolog-rlm"), runner=run)
        evidence = build_repository_evidence(
            {
                "root": "/srv/demo",
                "head": "a" * 40,
                "branch": "main",
                "dirty": False,
            }
        )
        frozen = "ok(frozen_spec{requirements:[]})"

        verify_repository_spec(bridge, frozen, evidence)

        _, kwargs = calls[0]
        _, evidence_input = kwargs["input"].split(".\n", 1)
        payload = json.loads(evidence_input)
        self.assertEqual(payload["branch"], "main")

    def test_trusted_registry_and_verify_bridge_bind_branch_assertion(self):
        provider = (ROOT / "prolog" / "zara_coding_assertions.pl").read_text(encoding="utf-8")
        adapter = (ROOT / "prolog" / "zara_coding_verify.pl").read_text(encoding="utf-8")
        self.assertIn("repository_branch,", provider)
        self.assertIn("repository_branch_args", provider)
        self.assertIn("repository_branch_evaluator", provider)
        self.assertIn("branch:text", provider)
        self.assertIn("repository_value(repository_branch", adapter)
        self.assertNotIn("assertz(", provider)
        self.assertNotIn("shell(", provider)


if __name__ == "__main__":
    unittest.main()
