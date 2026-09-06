import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError, RepositoryInspector


class InspectObjectIdTests(unittest.TestCase):
    def test_inspect_rejects_stable_malformed_head_object_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()

            def run(argv, **kwargs):
                args = argv[3:]
                outputs = {
                    ("rev-parse", "--show-toplevel"): f"{repo.resolve()}\n",
                    ("rev-parse", "HEAD"): "not-an-object-id\n",
                    ("symbolic-ref", "--short", "-q", "HEAD"): "main\n",
                    ("diff", "--name-only", "HEAD"): "",
                    ("ls-files", "--others", "--exclude-standard"): "",
                }
                return subprocess.CompletedProcess(argv, 0, stdout=outputs.get(tuple(args), ""), stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "malformed repository HEAD object ID"):
                inspector.inspect(repo)

    def test_inspect_accepts_sha1_and_sha256_head_object_ids(self):
        for object_id in ("a" * 40, "b" * 64):
            with self.subTest(length=len(object_id)), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                repo = root / "repo"
                repo.mkdir()

                def run(argv, **kwargs):
                    args = argv[3:]
                    outputs = {
                        ("rev-parse", "--show-toplevel"): f"{repo.resolve()}\n",
                        ("rev-parse", "HEAD"): object_id + "\n",
                        ("symbolic-ref", "--short", "-q", "HEAD"): "main\n",
                        ("diff", "--name-only", "HEAD"): "",
                        ("ls-files", "--others", "--exclude-standard"): "",
                    }
                    return subprocess.CompletedProcess(argv, 0, stdout=outputs.get(tuple(args), ""), stderr="")

                inspector = RepositoryInspector((root,), runner=run)
                self.assertEqual(inspector.inspect(repo)["head"], object_id)


if __name__ == "__main__":
    unittest.main()
