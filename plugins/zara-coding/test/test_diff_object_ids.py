import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError, RepositoryInspector


class DiffObjectIdTests(unittest.TestCase):
    def test_diff_rejects_stable_malformed_head_object_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()

            def run(argv, **kwargs):
                args = tuple(argv[3:])
                if args == ("rev-parse", "--show-toplevel"):
                    output = f"{repo.resolve()}\n"
                elif args == ("rev-parse", "HEAD"):
                    output = "not-an-object-id\n"
                elif args == ("diff", "--numstat", "--no-renames", "HEAD", "--"):
                    output = "1\t0\ttracked.txt\n"
                else:
                    output = ""
                return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "malformed diff HEAD object ID"):
                inspector.diff(repo)

    def test_diff_accepts_sha1_and_sha256_head_object_ids(self):
        for object_id in ("a" * 40, "b" * 64):
            with self.subTest(length=len(object_id)), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                repo = root / "repo"
                repo.mkdir()

                def run(argv, **kwargs):
                    args = tuple(argv[3:])
                    if args == ("rev-parse", "--show-toplevel"):
                        output = f"{repo.resolve()}\n"
                    elif args == ("rev-parse", "HEAD"):
                        output = object_id + "\n"
                    elif args == ("diff", "--numstat", "--no-renames", "HEAD", "--"):
                        output = "1\t0\ttracked.txt\n"
                    else:
                        output = ""
                    return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

                inspector = RepositoryInspector((root,), runner=run)
                self.assertEqual(inspector.diff(repo)[0]["path"], "tracked.txt")


if __name__ == "__main__":
    unittest.main()
