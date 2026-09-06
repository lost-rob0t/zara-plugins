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
    def test_task_survives_multiple_protocol_operations_and_requires_evidence(self) -> None:
        driver = ROOT / "prolog" / "zara_coding_task_state.pl"
        session = TaskStateSession(driver)
        self.addCleanup(session.stop)

        self.assertEqual(session.status(), {"status": "ok", "state": "ready"})
        created = session.create_task(
            "task-integration",
            goal="verify persistent state",
            constraints=["bounded"],
            dependencies=[],
            completion_criteria=["test-passed"],
        )
        rejected = session.complete_task("task-integration")
        session.record_evidence(
            "task-integration",
            kind="test",
            status="passed",
            detail="deterministic integration proof",
        )
        completed = session.complete_task("task-integration")
        fetched = session.get_task("task-integration")

        self.assertEqual(created["task"]["state"], "open")
        self.assertEqual(rejected["reason"], "verification-evidence-required")
        self.assertEqual(completed["task"]["state"], "completed")
        self.assertEqual(fetched["task"]["state"], "completed")
        self.assertEqual(len(fetched["task"]["evidence"]), 1)


if __name__ == "__main__":
    unittest.main()
