from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.task_state import TaskStateSession


class FakeProcess:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.stdin = io.StringIO()
        self.stdout = io.StringIO("".join(json.dumps(item) + "\n" for item in responses))
        self.stderr = io.StringIO()
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None) -> int:
        self.returncode = 0
        return 0


class RecordingStdout:
    def __init__(self, response: dict[str, object]) -> None:
        self._line = json.dumps(response) + "\n"
        self.readline_sizes: list[int] = []

    def readline(self, size: int = -1) -> str:
        self.readline_sizes.append(size)
        return self._line[:size] if size >= 0 else self._line


class TaskStateSessionTest(unittest.TestCase):
    def test_one_process_persists_across_task_operations(self) -> None:
        process = FakeProcess(
            [
                {"status": "ok", "task": {"id": "task-1", "state": "open"}},
                {"status": "ok", "task": {"id": "task-1", "state": "open"}},
            ]
        )
        calls = []

        def process_factory(argv, **kwargs):
            calls.append((argv, kwargs))
            return process

        session = TaskStateSession(Path("/tmp/driver.pl"), process_factory=process_factory)
        created = session.create_task(
            "task-1",
            goal="fix failing test",
            constraints=["repo-bound"],
            dependencies=["dep-1"],
            completion_criteria=["tests-green"],
        )
        fetched = session.get_task("task-1")

        self.assertEqual(created["task"]["id"], "task-1")
        self.assertEqual(fetched["task"]["id"], "task-1")
        self.assertEqual(len(calls), 1)
        commands = [json.loads(line) for line in process.stdin.getvalue().splitlines()]
        self.assertEqual(commands[0]["op"], "create")
        self.assertEqual(commands[1], {"op": "get", "task_id": "task-1"})

    def test_completion_fails_closed_until_verification_evidence_exists(self) -> None:
        process = FakeProcess(
            [
                {"status": "rejected", "reason": "verification-evidence-required"},
                {"status": "ok", "evidence": {"kind": "test", "status": "passed"}},
                {"status": "ok", "task": {"id": "task-1", "state": "completed"}},
            ]
        )
        session = TaskStateSession(Path("/tmp/driver.pl"), process_factory=lambda *args, **kwargs: process)

        rejected = session.complete_task("task-1")
        evidence = session.record_evidence("task-1", kind="test", status="passed", detail="unit suite")
        completed = session.complete_task("task-1")

        self.assertEqual(rejected, {"status": "rejected", "reason": "verification-evidence-required"})
        self.assertEqual(evidence["status"], "ok")
        self.assertEqual(completed["task"]["state"], "completed")

    def test_evidence_status_rejects_unsupported_values_before_writing(self) -> None:
        process = FakeProcess([])
        session = TaskStateSession(Path("/tmp/driver.pl"), process_factory=lambda *args, **kwargs: process)

        with self.assertRaisesRegex(ValueError, "status must be one of"):
            session.record_evidence("task-1", kind="test", status="unknown", detail="ambiguous")

        self.assertEqual(process.stdin.getvalue(), "")

    def test_protocol_rejects_oversized_fields_before_writing(self) -> None:
        process = FakeProcess([])
        session = TaskStateSession(Path("/tmp/driver.pl"), process_factory=lambda *args, **kwargs: process)

        with self.assertRaisesRegex(ValueError, "goal exceeds"):
            session.create_task("task-1", goal="x" * 4097)

        self.assertEqual(process.stdin.getvalue(), "")

    def test_protocol_bounds_stdout_read_before_allocating_response(self) -> None:
        process = FakeProcess([])
        stdout = RecordingStdout({"status": "ok", "state": "ready"})
        process.stdout = stdout
        session = TaskStateSession(Path("/tmp/driver.pl"), process_factory=lambda *args, **kwargs: process)

        self.assertEqual(session.status(), {"status": "ok", "state": "ready"})
        self.assertEqual(stdout.readline_sizes, [TaskStateSession.MAX_RESPONSE_CHARS + 1])

    def test_stop_terminates_the_owned_process(self) -> None:
        process = FakeProcess([])
        session = TaskStateSession(Path("/tmp/driver.pl"), process_factory=lambda *args, **kwargs: process)

        session.start()
        session.stop()

        self.assertTrue(process.terminated)


if __name__ == "__main__":
    unittest.main()
