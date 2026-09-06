import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_shell.domain import CommandPolicy, ShellError, ShellRunner


class SubprocessStringValidationTests(unittest.TestCase):
    def runner(self, root):
        return ShellRunner(
            CommandPolicy(
                allowed_programs={"python3"},
                allowed_roots=(root,),
                allowed_environment={"SAFE", "BAD=NAME"},
            )
        )

    def test_rejects_nul_argv_before_process_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = self.runner(root)
            with patch("zara_shell.domain.shutil.which", return_value="/usr/bin/python3"):
                with patch("zara_shell.domain.subprocess.Popen", side_effect=AssertionError("process created")):
                    with self.assertRaisesRegex(ShellError, "argv"):
                        runner.run(["python3", "bad\0arg"], cwd=root)

    def test_rejects_invalid_environment_strings_before_process_creation(self):
        cases = ({"SAFE": "bad\0value"}, {"BAD=NAME": "value"})
        for environment in cases:
            with self.subTest(environment=environment):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    runner = self.runner(root)
                    with patch("zara_shell.domain.shutil.which", return_value="/usr/bin/python3"):
                        with patch("zara_shell.domain.subprocess.Popen", side_effect=AssertionError("process created")):
                            with self.assertRaisesRegex(ShellError, "environment"):
                                runner.run(["python3", "-c", "pass"], cwd=root, env=environment)


if __name__ == "__main__":
    unittest.main()
