import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.repository_evidence import build_repository_evidence


class RepositoryEvidenceDuplicatePathTests(unittest.TestCase):
    def test_rejects_duplicate_changed_paths_before_symbolic_projection(self):
        snapshot = {
            "root": "/srv/demo",
            "head": "a" * 40,
            "branch": "main",
            "dirty": True,
            "changed_paths": ["src/app.py", "src/app.py"],
        }

        with self.assertRaisesRegex(ValueError, "duplicate.*changed path"):
            build_repository_evidence(snapshot)


if __name__ == "__main__":
    unittest.main()
