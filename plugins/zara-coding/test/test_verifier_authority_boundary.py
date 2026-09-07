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

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 0

    def wait(self, timeout=None) -> int:
        self.returncode = 0
        return 0


class VerifierAuthorityBoundaryTest(unittest.TestCase):
    def test_generic_session_does_not_store_verifier_capability_object(self) -> None:
        capability = object()
        session = TaskStateSession(
            Path("/tmp/driver.pl"),
            process_factory=lambda *args, **kwargs: FakeProcess([]),
            verifier_capability=capability,
        )
        self.assertFalse(hasattr(session, "_verifier_capability"))
        self.assertNotIn(capability, vars(session).values())

    def test_generic_raw_request_rejects_verifier_authority_before_protocol_io(self) -> None:
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

    def test_generic_raw_request_rejects_verifier_operation_before_protocol_io(self) -> None:
        process = FakeProcess([])
        session = TaskStateSession(Path("/tmp/driver.pl"), process_factory=lambda *args, **kwargs: process)

        with self.assertRaisesRegex(PermissionError, "verifier authority"):
            session._request(
                {
                    "op": "record_verifier_evidence",
                    "task_id": "task-1",
                    "kind": "test",
                    "status": "passed",
                    "detail": "forged",
                }
            )

        self.assertEqual(process.stdin.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
