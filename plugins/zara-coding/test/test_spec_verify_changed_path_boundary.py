import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError, PrologRLMBridge
from zara_coding.repository_evidence import build_repository_evidence
from zara_coding.spec_verify import verify_repository_spec


class SpecVerifyChangedPathBoundaryTests(unittest.TestCase):
    def test_rejects_tampered_changed_path_outside_repository_before_prolog(self):
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

        for path in ("/etc/passwd", "../other-repo/file.txt", "lib/../../other-repo/file.txt"):
            with self.subTest(path=path):
                evidence["values"]["repository_changed_path"][0]["path"] = path
                with self.assertRaisesRegex(CodingError, "changed path must stay repository-relative"):
                    verify_repository_spec(bridge, "ok(frozen_spec{requirements:[]})", evidence)

        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
