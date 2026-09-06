import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError, RepositoryInspector


class BranchObjectIdTests(unittest.TestCase):
    def test_branch_inventory_rejects_malformed_object_ids(self):
        for object_id in ("", "a" * 39, "a" * 41, "g" * 40, "not-an-object-id"):
            with self.subTest(object_id=object_id):
                with self.assertRaisesRegex(CodingError, "git branch inventory returned malformed object ID"):
                    RepositoryInspector._parse_branch_inventory(
                        f"main\t{object_id}\torigin/main\n",
                        limit=10,
                    )

    def test_branch_inventory_accepts_sha1_and_sha256_object_ids(self):
        for object_id in ("a" * 40, "b" * 64):
            with self.subTest(length=len(object_id)):
                self.assertEqual(
                    RepositoryInspector._parse_branch_inventory(
                        f"main\t{object_id}\torigin/main\n",
                        limit=10,
                    ),
                    [{"name": "main", "commit": object_id, "upstream": "origin/main"}],
                )

    def test_branches_reject_malformed_object_id_through_public_surface(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()

            def run(argv, **kwargs):
                args = tuple(argv[3:])
                if args == ("rev-parse", "--show-toplevel"):
                    output = f"{repo.resolve()}\n"
                elif args and args[0] == "for-each-ref":
                    output = "main\tnot-an-object-id\torigin/main\n"
                else:
                    output = ""
                return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "git branch inventory returned malformed object ID"):
                inspector.branches(repo, limit=1)


if __name__ == "__main__":
    unittest.main()
