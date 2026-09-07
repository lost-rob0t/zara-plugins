from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_emacs.config import EmacsConfig, EmacsConfigError


class EmacsConfigTypeTests(unittest.TestCase):
    def test_rejects_non_string_command_and_server(self) -> None:
        for key in ("emacsclient", "server_name"):
            for value in (None, True, 1, b"value"):
                with self.subTest(key=key, value=value):
                    with self.assertRaises(EmacsConfigError):
                        EmacsConfig.load({key: value})

    def test_rejects_non_string_project_descriptors(self) -> None:
        for projects in ({1: "/srv/project"}, {"demo": 1}, {"demo": None}):
            with self.subTest(projects=projects):
                with self.assertRaises(EmacsConfigError):
                    EmacsConfig.load({"projects": projects})

    def test_rejects_malformed_timeout(self) -> None:
        for timeout in (True, False, "5", None, math.nan, math.inf, -math.inf):
            with self.subTest(timeout=timeout):
                with self.assertRaises(EmacsConfigError):
                    EmacsConfig.load({"timeout_seconds": timeout})

    def test_accepts_typed_configuration(self) -> None:
        config = EmacsConfig.load(
            {
                "emacsclient": "emacsclient",
                "server_name": "server",
                "timeout_seconds": 0.25,
                "projects": {"demo": "/srv/demo"},
            }
        )
        self.assertEqual(0.25, config.timeout_seconds)
        self.assertEqual({"demo": "/srv/demo"}, config.projects)


if __name__ == "__main__":
    unittest.main()
