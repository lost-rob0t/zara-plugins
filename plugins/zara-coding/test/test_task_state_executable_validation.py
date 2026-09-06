import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.task_state import TaskStateSession


class TaskStateExecutableValidationTests(unittest.TestCase):
    def test_rejects_malformed_executable_before_spawn(self):
        for executable in (7, [], "", "   ", "swipl\x00oops", "swipl\n-q", "swipl\r-q"):
            with self.subTest(executable=executable):
                calls = []

                def process_factory(*args, **kwargs):
                    calls.append((args, kwargs))
                    raise AssertionError("invalid executable must not spawn")

                with self.assertRaises(ValueError):
                    TaskStateSession(
                        Path("/tmp/driver.pl"),
                        executable=executable,
                        process_factory=process_factory,
                    )

                self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
