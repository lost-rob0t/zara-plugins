import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.repository_evidence import build_repository_evidence


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
