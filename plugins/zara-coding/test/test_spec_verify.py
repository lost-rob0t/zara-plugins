import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError, PrologRLMBridge
from zara_coding.repository_evidence import build_repository_evidence
from zara_coding.spec_verify import verify_repository_spec


class RepositorySpecVerifyTests(unittest.TestCase):
    def test_verify_passes_frozen_spec_and_repository_evidence_over_stdin(self):
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
        frozen = "ok(frozen_spec{ref:spec_ref{series:zara_coding,version:1,fingerprint:'spec-sha256-deadbeef'}})"
        evidence = build_repository_evidence(
            {
                "root": "/srv/demo",
                "head": "a" * 40,
                "dirty": False,
            }
        )

        result = verify_repository_spec(bridge, frozen, evidence)

        self.assertEqual(result["status"], "ok")
        argv, kwargs = calls[0]
        self.assertFalse(kwargs["shell"])
        self.assertNotIn(frozen, " ".join(argv))
        self.assertNotIn("/srv/demo", " ".join(argv))
        self.assertIn("rlm_verify.pl", " ".join(argv))
        self.assertIn("zara_coding_verify.pl", " ".join(argv))
        goal = argv[argv.index("-g") + 1]
        self.assertIn("json_read_dict(user_input,E)", goal)
        self.assertIn("zara_coding_verify:verify_repository(F,E,O)", goal)

        frozen_input, evidence_input = kwargs["input"].split(".\n", 1)
        self.assertEqual(frozen_input, frozen)
        payload = json.loads(evidence_input)
        self.assertEqual(payload["root"], "/srv/demo")
        self.assertEqual(payload["head"], "a" * 40)
        self.assertFalse(payload["dirty"])

    def test_verify_rejects_non_repository_evidence_before_prolog(self):
        bridge = PrologRLMBridge(
            Path("/srv/prolog-rlm"),
            runner=lambda *args, **kwargs: self.fail("runner must not be called"),
        )
        evidence = build_repository_evidence(
            {
                "root": "/srv/demo",
                "head": "a" * 40,
                "dirty": False,
            }
        )
        evidence["source_class"] = "model_claim"

        with self.assertRaisesRegex(CodingError, "repository evidence"):
            verify_repository_spec(bridge, "ok(frozen_spec{})", evidence)

    def test_verify_rejects_non_frozen_outcome_before_prolog(self):
        bridge = PrologRLMBridge(
            Path("/srv/prolog-rlm"),
            runner=lambda *args, **kwargs: self.fail("runner must not be called"),
        )
        evidence = build_repository_evidence(
            {
                "root": "/srv/demo",
                "head": "a" * 40,
                "dirty": False,
            }
        )

        with self.assertRaisesRegex(CodingError, "frozen SPEC"):
            verify_repository_spec(bridge, "error(spec_lang_error{})", evidence)

    def test_prolog_bridge_binds_observations_to_frozen_requirement_identity(self):
        source = (ROOT / "prolog" / "zara_coding_verify.pl").read_text(encoding="utf-8")
        self.assertIn("requirement_id:Requirement.id", source)
        self.assertIn("assertion:Requirement.assertion", source)
        self.assertIn("verifier:Requirement.verifier", source)
        self.assertIn("collector:Requirement.collector", source)
        self.assertIn("source_class:repository", source)
        self.assertIn("trust_class:observed", source)
        self.assertIn("freshness:current", source)
        self.assertIn("rlm_verify:spec_verify", source)
        self.assertNotIn("assertz(", source)
        self.assertNotIn("consult(", source)
        self.assertNotIn("shell(", source)


if __name__ == "__main__":
    unittest.main()
