import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_shell.domain import CommandPolicy


class RuntimeBoundValidationTest(unittest.TestCase):
    def test_runtime_bound_rejects_nan(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite positive"):
            CommandPolicy(
                allowed_programs={"printf"},
                allowed_roots=(Path("/tmp"),),
                max_runtime_seconds=math.nan,
            )

    def test_runtime_bound_rejects_positive_infinity(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite positive"):
            CommandPolicy(
                allowed_programs={"printf"},
                allowed_roots=(Path("/tmp"),),
                max_runtime_seconds=math.inf,
            )


if __name__ == "__main__":
    unittest.main()
