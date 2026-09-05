import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))


class WorktreeAbsentAssertionTests(unittest.TestCase):
    def test_prolog_registry_defines_worktree_absence_as_pure_observed_verification(self):
        provider = (ROOT / "prolog" / "zara_coding_assertions.pl").read_text(encoding="utf-8")
        adapter = (ROOT / "prolog" / "zara_coding_verify.pl").read_text(encoding="utf-8")

        self.assertIn("worktree_absent,", provider)
        self.assertIn("worktree_absent_args", provider)
        self.assertIn("worktree_absent_evaluator", provider)
        self.assertIn("description:\"require one worktree path to be absent", provider)
        self.assertIn("repository_value(worktree_absent", adapter)
        self.assertIn("present:false", adapter)
        self.assertNotIn("assertz(", adapter)
        self.assertNotIn("shell(", adapter)


if __name__ == "__main__":
    unittest.main()
