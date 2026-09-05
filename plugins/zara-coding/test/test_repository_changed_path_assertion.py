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


class RepositoryChangedPathAssertionTests(unittest.TestCase):
    def test_repository_evidence_projects_bounded_changed_paths(self):
        evidence = build_repository_evidence(
            {
                "root": "/srv/demo",
                "head": "a" * 40,
                "branch": "main",
                "dirty": True,
                "changed_paths": ["lib/a.py", "test/test_a.py"],
            }
        )

        self.assertEqual(
            evidence["values"]["repository_changed_path"],
            [
                {"root": "/srv/demo", "path": "lib/a.py"},
                {"root": "/srv/demo", "path": "test/test_a.py"},
            ],
        )

    def test_repository_evidence_rejects_unbounded_or_malformed_changed_paths(self):
        snapshot = {
            "root": "/srv/demo",
            "head": "a" * 40,
            "branch": "main",
            "dirty": True,
            "changed_paths": [f"file-{index}.txt" for index in range(101)],
        }
        with self.assertRaisesRegex(ValueError, "changed path evidence exceeds 100 entries"):
            build_repository_evidence(snapshot)

        snapshot["changed_paths"] = [""]
        with self.assertRaisesRegex(ValueError, "changed path evidence must be non-empty text"):
            build_repository_evidence(snapshot)

    def test_repository_evidence_rejects_dirty_changed_path_contradictions(self):
        base = {
            "root": "/srv/demo",
            "head": "a" * 40,
            "branch": "main",
        }
        with self.assertRaisesRegex(ValueError, "dirty state contradicts changed paths"):
            build_repository_evidence({**base, "dirty": False, "changed_paths": ["lib/a.py"]})
        with self.assertRaisesRegex(ValueError, "dirty state contradicts changed paths"):
            build_repository_evidence({**base, "dirty": True, "changed_paths": []})

    def test_verify_payload_contains_only_bounded_changed_path_strings(self):
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, stdout="ok(verification_report{status:passed})\n", stderr="")

        bridge = PrologRLMBridge(Path("/srv/prolog-rlm"), runner=run)
        evidence = build_repository_evidence(
            {
                "root": "/srv/demo",
                "head": "a" * 40,
                "branch": "main",
                "dirty": True,
                "changed_paths": ["lib/a.py", "test/test_a.py"],
            }
        )

        verify_repository_spec(bridge, "ok(frozen_spec{requirements:[]})", evidence)

        _, kwargs = calls[0]
        _, evidence_input = kwargs["input"].split(".\n", 1)
        payload = json.loads(evidence_input)
        self.assertEqual(payload["changed_paths"], ["lib/a.py", "test/test_a.py"])

    def test_verify_rejects_tampered_dirty_changed_path_contradiction_before_prolog(self):
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, stdout="ok(verification_report{status:passed})\n", stderr="")

        bridge = PrologRLMBridge(Path("/srv/prolog-rlm"), runner=run)
        evidence = build_repository_evidence(
            {
                "root": "/srv/demo",
                "head": "a" * 40,
                "branch": "main",
                "dirty": True,
                "changed_paths": ["lib/a.py"],
            }
        )
        evidence["values"]["repository_clean"]["dirty"] = False

        with self.assertRaisesRegex(CodingError, "dirty state contradicts changed paths"):
            verify_repository_spec(bridge, "ok(frozen_spec{requirements:[]})", evidence)
        self.assertEqual(calls, [])

    def test_verify_rejects_tampered_state_ref_before_prolog(self):
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, stdout="ok(verification_report{status:passed})\n", stderr="")

        bridge = PrologRLMBridge(Path("/srv/prolog-rlm"), runner=run)
        evidence = build_repository_evidence(
            {
                "root": "/srv/demo",
                "head": "a" * 40,
                "branch": "main",
                "dirty": False,
                "changed_paths": [],
            }
        )
        evidence["state_ref"]["head"] = "b" * 40

        with self.assertRaisesRegex(CodingError, "state_ref does not match snapshot"):
            verify_repository_spec(bridge, "ok(frozen_spec{requirements:[]})", evidence)
        self.assertEqual(calls, [])

    def test_prolog_registry_defines_changed_path_as_pure_observed_verification(self):
        provider = (ROOT / "prolog" / "zara_coding_assertions.pl").read_text(encoding="utf-8")
        adapter = (ROOT / "prolog" / "zara_coding_verify.pl").read_text(encoding="utf-8")

        self.assertIn("repository_changed_path,", provider)
        self.assertIn("repository_changed_path_args", provider)
        self.assertIn("repository_changed_path_evaluator", provider)
        self.assertIn("repository_value(repository_changed_path", adapter)
        self.assertIn("changed_paths", adapter)
        self.assertNotIn("assertz(", adapter)
        self.assertNotIn("shell(", adapter)


if __name__ == "__main__":
    unittest.main()
