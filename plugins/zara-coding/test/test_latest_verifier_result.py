from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.task_state import TaskStateSession


@unittest.skipUnless(shutil.which("swipl"), "SWI-Prolog is not installed")
class LatestVerifierResultTest(unittest.TestCase):
    def setUp(self) -> None:
        driver = ROOT / "prolog" / "zara_coding_task_state.pl"
        self.session = TaskStateSession(driver)
        self.addCleanup(self.session.stop)

    def test_later_failure_revokes_earlier_pass_for_same_verifier(self) -> None:
        self.session.create_task(
            "task-regressed",
            goal="do not complete after regression",
            completion_criteria=["tests-green"],
        )
        self.session.record_evidence(
            "task-regressed",
            kind="test",
            status="passed",
            detail="suite passed",
        )
        self.session.record_evidence(
            "task-regressed",
            kind="test",
            status="failed",
            detail="suite regressed",
        )

        rejected = self.session.complete_task("task-regressed")
        fetched = self.session.get_task("task-regressed")

        self.assertEqual(rejected, {"status": "rejected", "reason": "passing-verification-required"})
        self.assertEqual(fetched["task"]["state"], "open")
        self.assertEqual([item["status"] for item in fetched["task"]["evidence"]], ["passed", "failed"])

    def test_current_failure_in_another_verifier_blocks_completion(self) -> None:
        self.session.create_task(
            "task-mixed-verifiers",
            goal="require all current verifier results to pass",
            completion_criteria=["tests-green", "build-green"],
        )
        self.session.record_evidence(
            "task-mixed-verifiers",
            kind="test",
            status="passed",
            detail="suite passed",
        )
        self.session.record_evidence(
            "task-mixed-verifiers",
            kind="build",
            status="failed",
            detail="build failed",
        )

        rejected = self.session.complete_task("task-mixed-verifiers")
        fetched = self.session.get_task("task-mixed-verifiers")

        self.assertEqual(rejected, {"status": "rejected", "reason": "passing-verification-required"})
        self.assertEqual(fetched["task"]["state"], "open")
        self.assertEqual(
            [(item["kind"], item["status"]) for item in fetched["task"]["evidence"]],
            [("test", "passed"), ("build", "failed")],
        )


if __name__ == "__main__":
    unittest.main()
