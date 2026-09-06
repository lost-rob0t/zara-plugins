import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_shell.domain import CommandPolicy


class PolicyDescriptorValidationTests(unittest.TestCase):
    def test_rejects_malformed_allowed_programs(self):
        for programs in ({""}, {7}, {"printf", None}):
            with self.subTest(programs=programs):
                with self.assertRaisesRegex(ValueError, "allowed_programs"):
                    CommandPolicy(allowed_programs=programs, allowed_roots=(Path("/tmp"),))

    def test_rejects_malformed_allowed_roots(self):
        for roots in (("",), (None,), (7,)):
            with self.subTest(roots=roots):
                with self.assertRaisesRegex(ValueError, "allowed_roots"):
                    CommandPolicy(allowed_programs={"printf"}, allowed_roots=roots)


if __name__ == "__main__":
    unittest.main()
