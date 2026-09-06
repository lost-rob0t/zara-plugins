import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import PrologRLMBridge


class PrologBridgeDescriptorValidationTests(unittest.TestCase):
    def test_rejects_malformed_timeout(self):
        for timeout in (True, False, 0, -1, "5", math.nan, math.inf, -math.inf):
            with self.subTest(timeout=timeout):
                with self.assertRaisesRegex(ValueError, "timeout_seconds"):
                    PrologRLMBridge(Path("/tmp"), timeout_seconds=timeout)

    def test_rejects_malformed_executable(self):
        for executable in (None, 7, False, "", " swipl", "swipl\n-q"):
            with self.subTest(executable=executable):
                with self.assertRaisesRegex(ValueError, "executable"):
                    PrologRLMBridge(Path("/tmp"), executable=executable)


if __name__ == "__main__":
    unittest.main()
