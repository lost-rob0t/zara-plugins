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


if __name__ == "__main__":
    unittest.main()
