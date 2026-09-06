import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError, RepositoryInspector


class BranchObjectIdTests(unittest.TestCase):
    def test_branch_inventory_rejects_malformed_object_id(self):
        with self.assertRaisesRegex(CodingError, "malformed object ID"):
            RepositoryInspector._parse_branch_inventory(
                "main\tnot-an-object-id\torigin/main\n",
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


if __name__ == "__main__":
    unittest.main()
