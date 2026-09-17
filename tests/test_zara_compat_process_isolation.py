from __future__ import annotations

import json
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path

from scripts.zara_compat import run_compatibility_process


class ZaraCompatibilityProcessIsolationTest(unittest.TestCase):
    @staticmethod
    def _script(root: Path, body: str) -> Path:
        path = root / "worker.py"
        path.write_text(body, encoding="utf-8")
        return path

    def test_native_crash_is_reported_without_killing_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = root / "result.json"
            script = self._script(
                root,
                "import os, signal\nos.kill(os.getpid(), signal.SIGSEGV)\n",
            )

            observed = run_compatibility_process(
                [sys.executable, str(script)],
                result,
                timeout=2.0,
            )

            self.assertEqual(observed["status"], "crashed")
            self.assertEqual(observed["signal"], "SIGSEGV")

    def test_hung_worker_is_killed_at_process_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = root / "result.json"
            script = self._script(root, "import time\ntime.sleep(30)\n")

            started = time.monotonic()
            observed = run_compatibility_process(
                [sys.executable, str(script)],
                result,
                timeout=0.1,
            )

            self.assertEqual(observed["status"], "timeout")
            self.assertLess(time.monotonic() - started, 2.0)

    def test_missing_result_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = root / "result.json"
            script = self._script(root, "raise SystemExit(0)\n")

            observed = run_compatibility_process(
                [sys.executable, str(script)],
                result,
                timeout=2.0,
            )

            self.assertEqual(observed["status"], "invalid-result")

    def test_malformed_result_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = root / "result.json"
            script = self._script(
                root,
                "from pathlib import Path\n"
                f"Path({str(result)!r}).write_text('not-json', encoding='utf-8')\n",
            )

            observed = run_compatibility_process(
                [sys.executable, str(script)],
                result,
                timeout=2.0,
            )

            self.assertEqual(observed["status"], "invalid-result")

    def test_valid_bounded_result_is_returned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = root / "result.json"
            payload = {"status": "passed", "tool_names": ["example.read"]}
            script = self._script(
                root,
                "import json\nfrom pathlib import Path\n"
                f"Path({str(result)!r}).write_text(json.dumps({payload!r}), encoding='utf-8')\n",
            )

            observed = run_compatibility_process(
                [sys.executable, str(script)],
                result,
                timeout=2.0,
            )

            self.assertEqual(observed, payload)

    def test_oversized_result_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = root / "result.json"
            script = self._script(
                root,
                "from pathlib import Path\n"
                f"Path({str(result)!r}).write_text('x' * 70000, encoding='utf-8')\n",
            )

            observed = run_compatibility_process(
                [sys.executable, str(script)],
                result,
                timeout=2.0,
            )

            self.assertEqual(observed["status"], "invalid-result")
            self.assertIn("too large", observed["reason"])


if __name__ == "__main__":
    unittest.main()
