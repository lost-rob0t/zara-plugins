import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_shell.domain import CommandPolicy


class RuntimeLimitTypeTests(unittest.TestCase):
    def test_rejects_non_numeric_runtime_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for runtime in (None, "5", object()):
                with self.subTest(runtime=runtime):
                    with self.assertRaisesRegex(ValueError, "max_runtime_seconds"):
                        CommandPolicy({"true"}, (root,), max_runtime_seconds=runtime)


if __name__ == "__main__":
    unittest.main()
