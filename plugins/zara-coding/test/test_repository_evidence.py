import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.repository_evidence import build_repository_evidence


class RepositoryEvidenceTests(unittest.TestCase):
    def test_builds_current_observed_evidence_for_supported_assertions(self):
        snapshot = {
            "root": "/srv/demo",
            "head": "a" * 40,
            "branch": "main",
            "dirty": False,
            "changed_paths": [],
        }

        evidence = build_repository_evidence(snapshot)

        self.assertEqual(evidence["source_class"], "repository")
        self.assertEqual(evidence["trust_class"], "observed")
        self.assertEqual(evidence["freshness"], "current")
        self.assertEqual(evidence["snapshot"], {"root": "/srv/demo", "head": "a" * 40})
        self.assertEqual(evidence["state_ref"], {"root": "/srv/demo", "head": "a" * 40})
        self.assertEqual(
            evidence["values"],
            {
                "repository_head": {"root": "/srv/demo", "head": "a" * 40},
                "repository_branch": {"root": "/srv/demo", "branch": "main"},
                "repository_clean": {"root": "/srv/demo", "dirty": False},
                "worktree_locked": [],
            },
        )
        self.assertEqual(len(evidence["evidence_refs"]), 1)
        self.assertEqual(evidence["evidence_refs"][0]["kind"], "git_repository_snapshot")

    def test_rejects_incomplete_or_invalid_snapshot(self):
        with self.assertRaisesRegex(ValueError, "root"):
            build_repository_evidence({"head": "a" * 40, "branch": "main", "dirty": False})
        with self.assertRaisesRegex(ValueError, "head"):
            build_repository_evidence({"root": "/srv/demo", "head": "short", "branch": "main", "dirty": False})
        with self.assertRaisesRegex(ValueError, "branch"):
            build_repository_evidence({"root": "/srv/demo", "head": "a" * 40, "dirty": False})
        with self.assertRaisesRegex(ValueError, "dirty"):
            build_repository_evidence({"root": "/srv/demo", "head": "a" * 40, "branch": "main", "dirty": "no"})


if __name__ == "__main__":
    unittest.main()
