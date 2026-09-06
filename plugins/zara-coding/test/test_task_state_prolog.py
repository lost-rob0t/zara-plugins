from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.task_state import TaskStateSession


@unittest.skipUnless(shutil.which("swipl"), "SWI-Prolog is not installed")
class PrologTaskStateIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        driver = ROOT / "prolog" / "zara_coding_task_state.pl"
        self.session = TaskStateSession(driver)
        self.addCleanup(self.session.stop)

    def test_task_survives_multiple_protocol_operations_and_requires_evidence(self) -> None:
        self.assertEqual(self.session.status(), {"status": "ok", "state": "ready"})
        created = self.session.create_task(
            "task-integration",
            goal="verify persistent state",
            constraints=["bounded"],
            dependencies=[],
            completion_criteria=["test-passed"],
        )
        rejected = self.session.complete_task("task-integration")
        self.session.record_evidence(
            "task-integration",
            kind="test",
            status="passed",
            detail="deterministic integration proof",
        )
        completed = self.session.complete_task("task-integration")
        fetched = self.session.get_task("task-integration")

        self.assertEqual(created["task"]["state"], "open")
        self.assertEqual(rejected["reason"], "verification-evidence-required")
        self.assertEqual(completed["task"]["state"], "completed")
        self.assertEqual(fetched["task"]["state"], "completed")
        self.assertEqual(len(fetched["task"]["evidence"]), 1)

    def test_failed_only_evidence_does_not_complete_task(self) -> None:
        self.session.create_task(
            "task-failed",
            goal="do not false-green",
            completion_criteria=["tests-green"],
        )
        self.session.record_evidence(
            "task-failed",
            kind="test",
            status="failed",
            detail="suite failed",
        )

        rejected = self.session.complete_task("task-failed")
        fetched = self.session.get_task("task-failed")

        self.assertEqual(rejected, {"status": "rejected", "reason": "passing-verification-evidence-required"})
        self.assertEqual(fetched["task"]["state"], "open")
        self.assertEqual(fetched["task"]["evidence"][0]["status"], "failed")

    def test_session_rejects_more_than_64_tasks(self) -> None:
        for index in range(64):
            created = self.session.create_task(
                f"task-{index}",
                goal="bounded task",
                completion_criteria=["verified"],
            )
            self.assertEqual(created["status"], "ok")

        rejected = self.session.create_task(
            "task-overflow",
            goal="must be rejected",
            completion_criteria=["verified"],
        )

        self.assertEqual(rejected, {"status": "rejected", "reason": "task-limit-reached"})

    def test_task_rejects_more_than_64_evidence_records(self) -> None:
        self.session.create_task(
            "task-evidence",
            goal="bound evidence",
            completion_criteria=["verified"],
        )
        for index in range(64):
            recorded = self.session.record_evidence(
                "task-evidence",
                kind="test",
                status="passed",
                detail=f"proof-{index}",
            )
            self.assertEqual(recorded["status"], "ok")

        rejected = self.session.record_evidence(
            "task-evidence",
            kind="test",
            status="passed",
            detail="overflow",
        )

        self.assertEqual(rejected, {"status": "rejected", "reason": "evidence-limit-reached"})


if __name__ == "__main__":
    unittest.main()
