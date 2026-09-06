import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import RepositoryInspector


class InspectorDescriptorValidationTests(unittest.TestCase):
    def test_rejects_malformed_allowed_roots(self):
        for roots in (("",), (None,), (7,)):
            with self.subTest(roots=roots):
                with self.assertRaisesRegex(ValueError, "allowed_roots"):
                    RepositoryInspector(roots)

    def test_rejects_malformed_executable(self):
        for executable in (None, 7, False, "", "git\n--version"):
            with self.subTest(executable=executable):
                with self.assertRaisesRegex(ValueError, "executable"):
                    RepositoryInspector((Path("/tmp"),), executable=executable)


if __name__ == "__main__":
    unittest.main()
