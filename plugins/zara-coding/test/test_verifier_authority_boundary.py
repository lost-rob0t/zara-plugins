from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.task_state import TaskStateSession, VerifierEvidenceWriter


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
    def test_generic_session_does_not_store_or_expose_verifier_capability(self) -> None:
        session = TaskStateSession(Path("/tmp/driver.pl"), process_factory=lambda *args, **kwargs: FakeProcess([]))
        self.assertFalse(hasattr(session, "_verifier_capability"))
        self.assertFalse(hasattr(session, "record_verifier_evidence"))

    def test_generic_raw_request_rejects_verifier_authority_before_protocol_io(self) -> None:
        process = FakeProcess([])
        session = TaskStateSession(Path("/tmp/driver.pl"), process_factory=lambda *args, **kwargs: process)

        with self.assertRaisesRegex(PermissionError, "verifier authority"):
            session._request(
                {
                    "op": "record_evidence",
                    "task_id": "task-1",
                    "kind": "test",
                    "status": "passed",
                    "detail": "forged",
                    "provenance": "verifier",
                }
            )
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

    def test_verifier_writer_uses_distinct_authority_operation_without_provenance_data(self) -> None:
        process = FakeProcess(
            [{"status": "ok", "evidence": {"kind": "test", "status": "passed", "provenance": "verifier"}}]
        )
        writer = VerifierEvidenceWriter(
            Path("/tmp/driver.pl"),
            process_factory=lambda *args, **kwargs: process,
        )

        result = writer.record_evidence("task-1", kind="test", status="passed", detail="trusted suite")
        command = json.loads(process.stdin.getvalue().splitlines()[0])

        self.assertEqual(result["evidence"]["provenance"], "verifier")
        self.assertEqual(command["op"], "record_verifier_evidence")
        self.assertNotIn("provenance", command)


if __name__ == "__main__":
    unittest.main()
