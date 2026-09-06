from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import PrologRLMBridge


class PrologRLMPolicyDescriptorTests(unittest.TestCase):
    def test_requires_path_checkout(self) -> None:
        with self.assertRaises(ValueError):
            PrologRLMBridge("/srv/prolog-rlm")  # type: ignore[arg-type]

    def test_rejects_malformed_executable_before_process_use(self) -> None:
        for executable in (None, True, 1, "", " swipl", "swipl ", "swipl\n"):
            with self.subTest(executable=executable):
                with self.assertRaises(ValueError):
                    PrologRLMBridge(Path("/srv/prolog-rlm"), executable=executable)  # type: ignore[arg-type]

    def test_rejects_malformed_timeout_before_process_use(self) -> None:
        for timeout in (True, False, 0, -1, math.nan, math.inf, -math.inf, "5"):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    PrologRLMBridge(Path("/srv/prolog-rlm"), timeout_seconds=timeout)  # type: ignore[arg-type]

    def test_accepts_finite_positive_numeric_timeout(self) -> None:
        self.assertEqual(
            5,
            PrologRLMBridge(Path("/srv/prolog-rlm"), timeout_seconds=5, runner=lambda *args, **kwargs: None).timeout_seconds,
        )
        self.assertEqual(
            0.25,
            PrologRLMBridge(
                Path("/srv/prolog-rlm"),
                timeout_seconds=0.25,
                runner=lambda *args, **kwargs: None,
            ).timeout_seconds,
        )


if __name__ == "__main__":
    unittest.main()
