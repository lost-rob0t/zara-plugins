import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.repository_evidence import build_repository_evidence


class RepositoryEvidenceDuplicatePathTests(unittest.TestCase):
    def snapshot(self, changed_paths):
        return {
            "root": "/srv/demo",
            "head": "a" * 40,
            "branch": "main",
            "dirty": True,
            "changed_paths": changed_paths,
        }

    def test_rejects_duplicate_changed_paths_before_symbolic_projection(self):
        with self.assertRaisesRegex(ValueError, "duplicate.*changed path"):
            build_repository_evidence(self.snapshot(["src/app.py", "src/app.py"]))

    def test_rejects_noncanonical_changed_path_aliases(self):
        for path in ("./src/app.py", "src//app.py", "src/./app.py", "."):
            with self.subTest(path=path):
                with self.assertRaisesRegex(ValueError, "canonical"):
                    build_repository_evidence(self.snapshot([path]))

    def test_rejects_aliases_that_could_hide_duplicate_paths(self):
        with self.assertRaisesRegex(ValueError, "canonical"):
            build_repository_evidence(self.snapshot(["src/app.py", "src//app.py"]))


if __name__ == "__main__":
    unittest.main()
