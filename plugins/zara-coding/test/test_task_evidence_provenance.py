from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "prolog" / "zara_coding_task_state.pl"


@unittest.skipUnless(shutil.which("swipl"), "SWI-Prolog is required")
class TaskEvidenceProvenanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.process = subprocess.Popen(
            ["swipl", "-q", "-s", str(DRIVER), "-g", "zara_coding_task_state:serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def tearDown(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=2)

    def request(self, payload: dict[str, object]) -> dict[str, object]:
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        self.process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        self.assertTrue(line)
        return json.loads(line)

    def create_task(self, task_id: str) -> None:
        response = self.request(
            {
                "op": "create",
                "task_id": task_id,
                "goal": "verify exact head",
                "repository": None,
                "constraints": [],
                "dependencies": [],
                "completion_criteria": ["tests-pass"],
            }
        )
        self.assertEqual(response["status"], "ok")

    def test_caller_authored_pass_cannot_complete_task(self) -> None:
        self.create_task("caller-pass")

        recorded = self.request(
            {
                "op": "record_evidence",
                "task_id": "caller-pass",
                "kind": "tests",
                "status": "passed",
                "detail": "model says green",
                "provenance": "caller",
            }
        )

        self.assertEqual(
            recorded,
            {"status": "rejected", "reason": "passing-evidence-requires-verifier"},
        )
        completed = self.request({"op": "complete", "task_id": "caller-pass"})
        self.assertEqual(
            completed,
            {"status": "rejected", "reason": "verification-evidence-required"},
        )

    def test_verifier_pass_is_retained_with_provenance_and_can_complete(self) -> None:
        self.create_task("verifier-pass")

        recorded = self.request(
            {
                "op": "record_evidence",
                "task_id": "verifier-pass",
                "kind": "tests",
                "status": "passed",
                "detail": "pytest exit=0 head=abc",
                "provenance": "verifier",
            }
        )

        self.assertEqual(recorded["status"], "ok")
        self.assertEqual(recorded["evidence"]["provenance"], "verifier")
        completed = self.request({"op": "complete", "task_id": "verifier-pass"})
        self.assertEqual(completed["status"], "ok")
        self.assertEqual(completed["task"]["state"], "completed")

    def test_unknown_provenance_fails_closed(self) -> None:
        self.create_task("unknown-provenance")

        recorded = self.request(
            {
                "op": "record_evidence",
                "task_id": "unknown-provenance",
                "kind": "tests",
                "status": "failed",
                "detail": "1 failed",
                "provenance": "model",
            }
        )

        self.assertEqual(
            recorded,
            {"status": "rejected", "reason": "unsupported-evidence-provenance"},
        )


if __name__ == "__main__":
    unittest.main()
