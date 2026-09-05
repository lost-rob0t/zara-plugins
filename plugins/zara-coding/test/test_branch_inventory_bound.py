import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError, RepositoryInspector


class BranchInventoryBoundTests(unittest.TestCase):
    def test_branch_inventory_fails_closed_when_more_refs_exist_than_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()

            def run(argv, **kwargs):
                args = tuple(argv[3:])
                if args == ("rev-parse", "--show-toplevel"):
                    output = f"{repo.resolve()}\n"
                elif args[0] == "for-each-ref":
                    output = (
                        f"alpha\t{'a' * 40}\t\n"
                        f"beta\t{'b' * 40}\t\n"
                        f"gamma\t{'c' * 40}\t\n"
                    )
                else:
                    output = ""
                return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "exceeds branch limit of 2"):
                inspector.branches(repo, limit=2)


if __name__ == "__main__":
    unittest.main()
