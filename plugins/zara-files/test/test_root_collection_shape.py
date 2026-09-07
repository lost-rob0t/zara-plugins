import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_files.files import FileDomain, FileDomainError


class RootCollectionShapeTest(unittest.TestCase):
    def test_scalar_root_never_becomes_a_configured_filesystem_root(self):
        with self.assertRaisesRegex(FileDomainError, "roots"):
            FileDomain("/")

    def test_malformed_root_collection_shapes_fail_structurally(self):
        for malformed in (b"/tmp", {"root": "/tmp"}, 7, None):
            with self.subTest(roots=malformed):
                with self.assertRaisesRegex(FileDomainError, "roots"):
                    FileDomain(malformed)

    def test_explicit_root_collection_preserves_valid_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            domain = FileDomain([Path(tmp)])
            self.assertEqual(domain.root_ids, ("root-0",))


if __name__ == "__main__":
    unittest.main()
