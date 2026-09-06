import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_shell.domain import CommandPolicy


class PolicyCollectionShapeTests(unittest.TestCase):
    def test_rejects_scalar_allowed_roots(self):
        with self.assertRaisesRegex(ValueError, "allowed_roots"):
            CommandPolicy(allowed_programs={"printf"}, allowed_roots="/tmp")

    def test_rejects_scalar_allowed_programs(self):
        with self.assertRaisesRegex(ValueError, "allowed_programs"):
            CommandPolicy(allowed_programs="printf", allowed_roots=(Path("/tmp"),))

    def test_rejects_scalar_allowed_environment(self):
        with self.assertRaisesRegex(ValueError, "allowed_environment"):
            CommandPolicy(
                allowed_programs={"printf"},
                allowed_roots=(Path("/tmp"),),
                allowed_environment="PATH",
            )


if __name__ == "__main__":
    unittest.main()
