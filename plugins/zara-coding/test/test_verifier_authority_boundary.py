from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.task_state import TaskStateSession, create_task_state_interfaces


class FakeProcess:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.stdin = io.StringIO()
        self.stdout = io.StringIO("".join(json.dumps(item) + "\n" for item in responses))
        self.stderr = io.StringIO()
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 0

    def wait(self, timeout=None) -> int:
        self.returncode = 0
        return 0


class VerifierAuthorityBoundaryTest(unittest.TestCase):
    def test_generic_session_has_no_raw_protocol_or_process_authority(self) -> None:
        process = FakeProcess([])
        session, _verifier = create_task_state_interfaces(
            Path("/tmp/driver.pl"),
            process_factory=lambda *args, **kwargs: process,
        )
        self.assertFalse(hasattr(session, "_request_protocol"))
        self.assertFalse(hasattr(session, "_process"))
        self.assertFalse(hasattr(session, "_verifier_capability_id"))
        self.assertFalse(hasattr(session, "record_verifier_evidence"))

    def test_generic_session_rejects_verifier_authority_before_protocol_io(self) -> None:
        process = FakeProcess([])
        session = TaskStateSession(Path("/tmp/driver.pl"), process_factory=lambda *args, **kwargs: process)

        forged = {
            "op": "record_evidence",
            "task_id": "task-1",
            "kind": "test",
            "status": "passed",
            "detail": "forged",
            "provenance": "verifier",
        }
        with self.assertRaisesRegex(PermissionError, "verifier authority"):
            session._request(forged)

        self.assertEqual(process.stdin.getvalue(), "")

    def test_verifier_writer_derives_trusted_operation_without_generic_replay(self) -> None:
        process = FakeProcess(
            [{"status": "ok", "evidence": {"kind": "test", "status": "passed", "provenance": "verifier"}}]
        )
        session, verifier = create_task_state_interfaces(
            Path("/tmp/driver.pl"),
            process_factory=lambda *args, **kwargs: process,
        )

        evidence = verifier.record_evidence("task-1", kind="test", status="passed", detail="suite green")
        command = json.loads(process.stdin.getvalue().splitlines()[0])

        self.assertEqual(evidence["evidence"]["provenance"], "verifier")
        self.assertEqual(command["op"], "record_verifier_evidence")
        self.assertNotIn("provenance", command)
        self.assertFalse(hasattr(session, "record_verifier_evidence"))


if __name__ == "__main__":
    unittest.main()
