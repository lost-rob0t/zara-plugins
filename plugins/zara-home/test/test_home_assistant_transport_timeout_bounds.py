import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_home.home_assistant_transport import HomeAssistantHTTPError, HomeAssistantHTTPTransport


class HomeAssistantHTTPTransportTimeoutBoundsTest(unittest.TestCase):
    def test_timeout_requires_finite_non_boolean_number(self):
        invalid = (True, False, None, "1", float("nan"), float("inf"), float("-inf"), 0, -1, 60.0001)
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaisesRegex(HomeAssistantHTTPError, "invalid-timeout"):
                    HomeAssistantHTTPTransport("http://127.0.0.1:8123", "token-a", timeout=value)

    def test_timeout_accepts_bounded_integer_or_float(self):
        for value in (1, 0.1, 60):
            with self.subTest(value=value):
                transport = HomeAssistantHTTPTransport("http://127.0.0.1:8123", "token-a", timeout=value)
                self.assertEqual(transport.timeout, float(value))
                self.assertTrue(math.isfinite(transport.timeout))


if __name__ == "__main__":
    unittest.main()
