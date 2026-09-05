import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError, RepositoryInspector


class RepositoryInspectBoundTests(unittest.TestCase):
    def test_inspect_fails_closed_above_changed_path_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            changed = "".join(f"tracked-{index}.txt\n" for index in range(101))

            def run(argv, **kwargs):
                args = tuple(argv[3:])
                outputs = {
                    ("rev-parse", "--show-toplevel"): f"{repo.resolve()}\n",
                    ("rev-parse", "HEAD"): "a" * 40 + "\n",
                    ("symbolic-ref", "--short", "-q", "HEAD"): "main\n",
                    ("diff", "--name-only", "HEAD"): changed,
                    ("ls-files", "--others", "--exclude-standard"): "",
                }
                return subprocess.CompletedProcess(argv, 0, stdout=outputs.get(args, ""), stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "changed path limit of 100"):
                inspector.inspect(repo)

    def test_inspect_deduplicates_before_enforcing_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            paths = "".join(f"file-{index}.txt\n" for index in range(100))

            def run(argv, **kwargs):
                args = tuple(argv[3:])
                outputs = {
                    ("rev-parse", "--show-toplevel"): f"{repo.resolve()}\n",
                    ("rev-parse", "HEAD"): "a" * 40 + "\n",
                    ("symbolic-ref", "--short", "-q", "HEAD"): "main\n",
                    ("diff", "--name-only", "HEAD"): paths,
                    ("ls-files", "--others", "--exclude-standard"): paths,
                }
                return subprocess.CompletedProcess(argv, 0, stdout=outputs.get(args, ""), stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            snapshot = inspector.inspect(repo)
            self.assertEqual(len(snapshot["changed_paths"]), 100)

    def test_inspect_rejects_repository_identity_change_during_snapshot(self):
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
                    output = ("a" if head_reads == 1 else "b") * 40 + "\n"
                elif args == ("symbolic-ref", "--short", "-q", "HEAD"):
                    output = "main\n"
                elif args == ("diff", "--name-only", "HEAD"):
                    output = "tracked.txt\n"
                elif args == ("ls-files", "--others", "--exclude-standard"):
                    output = ""
                else:
                    output = ""
                return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "identity changed during inspection"):
                inspector.inspect(repo)


if __name__ == "__main__":
    unittest.main()
