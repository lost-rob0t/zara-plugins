import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_pi.domain import TmuxBridge


class ControlSanitizationTests(unittest.TestCase):
    def test_isolated_escape_byte_never_reaches_model_or_ui_output(self):
        sanitized = TmuxBridge._sanitize("before\x1bafter")
        self.assertEqual(sanitized, "beforeafter")
        self.assertNotIn("\x1b", sanitized)


if __name__ == "__main__":
    unittest.main()
