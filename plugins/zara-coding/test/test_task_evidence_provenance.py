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

    def create_task(self, task_id: str, criteria: list[str]) -> None:
        response = self.request({
            "op": "create", "task_id": task_id, "goal": "verify exact head",
            "repository": None, "constraints": [], "dependencies": [],
            "completion_criteria": criteria,
        })
        self.assertEqual(response["status"], "ok")

    def verifier(self, task_id: str, kind: str, status: str) -> dict[str, object]:
        return self.request({
            "op": "record_evidence", "task_id": task_id, "kind": kind,
            "status": status, "detail": f"{kind} {status}", "provenance": "verifier",
        })

    def test_caller_authored_pass_is_rejected_inside_prolog(self) -> None:
        self.create_task("caller-pass", ["tests"])
        recorded = self.request({
            "op": "record_evidence", "task_id": "caller-pass", "kind": "tests",
            "status": "passed", "detail": "model says green", "provenance": "caller",
        })
        self.assertEqual(recorded, {"status": "rejected", "reason": "passing-evidence-requires-verifier"})
        self.assertEqual(
            self.request({"op": "complete", "task_id": "caller-pass"}),
            {"status": "rejected", "reason": "verification-evidence-required"},
        )

    def test_every_declared_criterion_requires_current_verifier_pass(self) -> None:
        self.create_task("multi", ["tests", "lint"])
        self.verifier("multi", "tests", "passed")
        self.assertEqual(
            self.request({"op": "complete", "task_id": "multi"}),
            {"status": "rejected", "reason": "passing-verification-required"},
        )
        self.verifier("multi", "lint", "passed")
        self.assertEqual(self.request({"op": "complete", "task_id": "multi"})["status"], "ok")

    def test_unrelated_pass_cannot_satisfy_criterion(self) -> None:
        self.create_task("wrong-kind", ["tests"])
        self.verifier("wrong-kind", "lint", "passed")
        self.assertEqual(
            self.request({"op": "complete", "task_id": "wrong-kind"}),
            {"status": "rejected", "reason": "passing-verification-required"},
        )

    def test_later_failure_revokes_prior_pass(self) -> None:
        self.create_task("regressed", ["tests"])
        self.verifier("regressed", "tests", "passed")
        self.verifier("regressed", "tests", "failed")
        self.assertEqual(
            self.request({"op": "complete", "task_id": "regressed"}),
            {"status": "rejected", "reason": "passing-verification-required"},
        )


if __name__ == "__main__":
    unittest.main()
