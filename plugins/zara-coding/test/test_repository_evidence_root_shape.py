import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.repository_evidence import build_repository_evidence


class RepositoryEvidenceRootShapeTests(unittest.TestCase):
    def _snapshot(self, root):
        return {
            "root": root,
            "head": "a" * 40,
            "branch": "main",
            "dirty": False,
            "changed_paths": [],
        }

    def test_rejects_relative_repository_root(self):
        with self.assertRaisesRegex(ValueError, "repository snapshot root must be absolute"):
            build_repository_evidence(self._snapshot("relative/repo"))

    def test_rejects_repository_root_with_nul(self):
        with self.assertRaisesRegex(ValueError, "repository snapshot root must not contain NUL"):
            build_repository_evidence(self._snapshot("/repo\x00escape"))


if __name__ == "__main__":
    unittest.main()
