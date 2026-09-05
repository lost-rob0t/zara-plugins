import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.repository_evidence import build_repository_evidence


class RepositoryEvidenceBranchShapeTests(unittest.TestCase):
    def _snapshot(self, branch):
        return {
            "root": "/repo",
            "head": "a" * 40,
            "branch": branch,
            "dirty": False,
            "changed_paths": [],
        }

    def test_rejects_branch_with_nul(self):
        with self.assertRaisesRegex(ValueError, "repository snapshot branch must be single-line text"):
            build_repository_evidence(self._snapshot("main\x00other"))

    def test_rejects_multiline_branch(self):
        with self.assertRaisesRegex(ValueError, "repository snapshot branch must be single-line text"):
            build_repository_evidence(self._snapshot("main\nother"))

    def test_accepts_detached_identity(self):
        evidence = build_repository_evidence(self._snapshot("DETACHED"))
        self.assertEqual(evidence["values"]["repository_branch"]["branch"], "DETACHED")


if __name__ == "__main__":
    unittest.main()
