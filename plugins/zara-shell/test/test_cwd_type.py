import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_shell.domain import CommandPolicy, ShellError, ShellRunner


class CwdTypeTests(unittest.TestCase):
    def test_malformed_cwd_fails_structurally_before_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner = ShellRunner(CommandPolicy(allowed_programs={"printf"}, allowed_roots=(root,)))
            for cwd in (0, False, object()):
                with self.subTest(cwd=cwd):
                    with patch("zara_shell.domain.subprocess.Popen") as popen:
                        with self.assertRaisesRegex(ShellError, "cwd must be path-like"):
                            runner.run(["printf", "ok"], cwd=cwd)
                        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
