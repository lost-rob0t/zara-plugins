import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError, RepositoryInspector


class BranchObjectIdValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def inspector_for(self, branch_output: str) -> RepositoryInspector:
        def run(argv, **kwargs):
            args = tuple(argv[3:])
            if args == ("rev-parse", "--show-toplevel"):
                output = f"{self.repo.resolve()}\n"
            elif args and args[0] == "for-each-ref":
                output = branch_output
            else:
                output = ""
            return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

        return RepositoryInspector((self.root,), runner=run)

    def test_branches_reject_malformed_object_id(self):
        inspector = self.inspector_for("main\tnot-an-object-id\torigin/main\n")
        with self.assertRaisesRegex(CodingError, "git branch inventory returned malformed object ID"):
            inspector.branches(self.repo, limit=1)

    def test_branches_accept_sha256_object_id(self):
        commit = "b" * 64
        inspector = self.inspector_for(f"main\t{commit}\torigin/main\n")
        self.assertEqual(
            inspector.branches(self.repo, limit=1),
            [{"name": "main", "commit": commit, "upstream": "origin/main"}],
        )


if __name__ == "__main__":
    unittest.main()
