import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError, RepositoryInspector


class DiffSnapshotIdentityTests(unittest.TestCase):
    def test_diff_rejects_repository_head_change_during_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            head_reads = 0

            def run(argv, **kwargs):
                nonlocal head_reads
                args = tuple(argv[3:])
                if args == ("rev-parse", "--show-toplevel"):
                    output = f"{repo.resolve()}\n"
                elif args == ("rev-parse", "HEAD"):
                    head_reads += 1
                    output = (("a" if head_reads == 1 else "b") * 40) + "\n"
                elif args == ("diff", "--numstat", "--no-renames", "HEAD", "--"):
                    output = "1\t0\ttracked.txt\n"
                else:
                    output = ""
                return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "identity changed during diff"):
                inspector.diff(repo)

    def test_diff_rejects_changed_numstat_evidence_during_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            diff_reads = 0

            def run(argv, **kwargs):
                nonlocal diff_reads
                args = tuple(argv[3:])
                if args == ("rev-parse", "--show-toplevel"):
                    output = f"{repo.resolve()}\n"
                elif args == ("rev-parse", "HEAD"):
                    output = "a" * 40 + "\n"
                elif args == ("diff", "--numstat", "--no-renames", "HEAD", "--"):
                    diff_reads += 1
                    output = "1\t0\ttracked.txt\n" if diff_reads == 1 else "2\t0\ttracked.txt\n"
                else:
                    output = ""
                return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "working tree changed during diff"):
                inspector.diff(repo)
            self.assertEqual(diff_reads, 2)


if __name__ == "__main__":
    unittest.main()
