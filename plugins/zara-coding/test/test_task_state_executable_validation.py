import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.task_state import TaskStateSession


class TaskStateExecutableValidationTests(unittest.TestCase):
    def test_rejects_malformed_executable_before_session_start(self):
        for executable in (7, object(), "   ", "swipl\0bad", "swipl\nbad", "swipl\rbad"):
            with self.subTest(executable=executable):
                with self.assertRaisesRegex(ValueError, "executable"):
                    TaskStateSession(Path("/tmp/zara-coding-task-state.pl"), executable=executable)


if __name__ == "__main__":
    unittest.main()
