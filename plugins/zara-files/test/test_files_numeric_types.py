import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_files.files import FileDomain, FileDomainError


class FileNumericTypeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "root"
        self.root.mkdir()
        (self.root / "note.txt").write_text("abcdef", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def test_constructor_limits_reject_coercive_descriptors(self):
        for key in ("max_read_bytes", "max_results"):
            for value in (True, False, "64", 64.5):
                with self.subTest(key=key, value=value):
                    kwargs = {"max_read_bytes": 128, "max_results": 8, key: value}
                    with self.assertRaises(FileDomainError):
                        FileDomain([self.root], **kwargs)

    def test_read_limit_rejects_coercive_descriptors(self):
        domain = FileDomain([self.root], max_read_bytes=128)
        for value in (True, False, "4", 4.5):
            with self.subTest(value=value):
                with self.assertRaises(FileDomainError):
                    domain.read_text("root-0", "note.txt", max_bytes=value)

    def test_canonical_integer_limits_still_work(self):
        domain = FileDomain([self.root], max_read_bytes=128, max_results=8)
        result = domain.read_text("root-0", "note.txt", max_bytes=4)
        self.assertEqual("abcd", result["text"])
        self.assertTrue(result["truncated"])


if __name__ == "__main__":
    unittest.main()
