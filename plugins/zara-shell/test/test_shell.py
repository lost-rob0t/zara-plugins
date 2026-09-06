import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_shell.domain import CommandPolicy, ShellError, ShellRunner


class ShellRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.policy = CommandPolicy(
            allowed_programs={"printf", "pwd"},
            allowed_roots=(self.root,),
            max_runtime_seconds=0.5,
            max_output_bytes=128,
            max_input_bytes=64,
        )
        self.runner = ShellRunner(self.policy)

    def tearDown(self):
        self.temporary.cleanup()

    def test_executes_argv_without_shell_interpolation(self):
        result = self.runner.run(["printf", "%s", "hello; echo pwned"], cwd=self.root)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["stdout"], "hello; echo pwned")
        self.assertEqual(result["stderr"], "")
        self.assertFalse(result["timed_out"])

    def test_refuses_unallowlisted_program(self):
        with self.assertRaisesRegex(ShellError, "not allowed"):
            self.runner.run(["sh", "-c", "echo pwned"], cwd=self.root)

    def test_refuses_cwd_outside_allowed_roots(self):
        with self.assertRaisesRegex(ShellError, "cwd"):
            self.runner.run(["pwd"], cwd=Path("/"))

    def test_env_is_explicit_and_bounded(self):
        with self.assertRaisesRegex(ShellError, "environment"):
            self.runner.run(["printf", "ok"], cwd=self.root, env={"SECRET": "x" * 4096})

    def test_stdin_limit_fails_before_execution(self):
        with self.assertRaisesRegex(ShellError, "input"):
            self.runner.run(["printf", "ok"], cwd=self.root, stdin="x" * 65)

    def test_policy_rejects_non_integer_byte_limits(self):
        for field, value in (
            ("max_output_bytes", 1.5),
            ("max_input_bytes", True),
            ("max_environment_bytes", 2.5),
        ):
            kwargs = {
                "allowed_programs": {"printf"},
                "allowed_roots": (self.root,),
                field: value,
            }
            with self.subTest(field=field, value=value):
                with self.assertRaisesRegex(ValueError, "byte limits must be positive integers"):
                    CommandPolicy(**kwargs)

    def test_timeout_is_reported_structurally(self):
        policy = CommandPolicy(
            allowed_programs={sys.executable},
            allowed_roots=(self.root,),
            max_runtime_seconds=0.05,
            max_output_bytes=128,
            max_input_bytes=64,
        )
        result = ShellRunner(policy).run([sys.executable, "-c", "import time; time.sleep(5)"], cwd=self.root)
        self.assertTrue(result["timed_out"])
        self.assertIsNone(result["exit_code"])

    def test_timeout_terminates_descendant_processes(self):
        marker = self.root / "escaped-child"
        child = (
            "import pathlib,time; "
            f"time.sleep(0.2); pathlib.Path({str(marker)!r}).write_text('escaped')"
        )
        parent = (
            "import subprocess,sys,time; "
            f"subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(5)"
        )
        policy = CommandPolicy(
            allowed_programs={sys.executable},
            allowed_roots=(self.root,),
            max_runtime_seconds=0.05,
            max_output_bytes=128,
            max_input_bytes=64,
        )
        result = ShellRunner(policy).run([sys.executable, "-c", parent], cwd=self.root)
        self.assertTrue(result["timed_out"])
        time.sleep(0.3)
        self.assertFalse(marker.exists())

    def test_output_is_bounded_and_reports_truncation(self):
        policy = CommandPolicy(
            allowed_programs={sys.executable},
            allowed_roots=(self.root,),
            max_runtime_seconds=0.5,
            max_output_bytes=16,
            max_input_bytes=64,
        )
        result = ShellRunner(policy).run([sys.executable, "-c", "print('x' * 100)"], cwd=self.root)
        self.assertLessEqual(len(result["stdout"].encode()), 16)
        self.assertTrue(result["stdout_truncated"])


if __name__ == "__main__":
    unittest.main()
