import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError, RepositoryInspector


class LogObjectIdValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def inspector_for(self, log_output: str) -> RepositoryInspector:
        def run(argv, **kwargs):
            args = argv[3:]
            if args == ["rev-parse", "--show-toplevel"]:
                return subprocess.CompletedProcess(argv, 0, stdout=f"{self.repo.resolve()}\n", stderr="")
            if args[:1] == ["log"]:
                return subprocess.CompletedProcess(argv, 0, stdout=log_output, stderr="")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        return RepositoryInspector((self.root,), runner=run)

    def test_log_rejects_malformed_commit_object_id(self):
        inspector = self.inspector_for(
            f"not-an-object-id\t{'a' * 40}\tAlice\t2026-09-05T10:00:00-04:00\tsubject\n"
        )
        with self.assertRaisesRegex(CodingError, "git log returned malformed object ID"):
            inspector.log(self.repo, limit=1)

    def test_log_rejects_malformed_parent_object_id(self):
        inspector = self.inspector_for(
            f"{'b' * 40}\t{'a' * 39}z\tAlice\t2026-09-05T10:00:00-04:00\tsubject\n"
        )
        with self.assertRaisesRegex(CodingError, "git log returned malformed object ID"):
            inspector.log(self.repo, limit=1)

    def test_log_accepts_sha256_object_ids(self):
        commit = "b" * 64
        parent = "a" * 64
        inspector = self.inspector_for(
            f"{commit}\t{parent}\tAlice\t2026-09-05T10:00:00-04:00\tsubject\n"
        )
        self.assertEqual(
            inspector.log(self.repo, limit=1)[0],
            {
                "commit": commit,
                "parents": [parent],
                "author": "Alice",
                "authored_at": "2026-09-05T10:00:00-04:00",
                "subject": "subject",
            },
        )


if __name__ == "__main__":
    unittest.main()
