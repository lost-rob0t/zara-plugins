from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.task_state import create_task_state_interfaces


@unittest.skipUnless(shutil.which("swipl"), "SWI-Prolog is not installed")
class PrologTaskStateIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        driver = ROOT / "prolog" / "zara_coding_task_state.pl"
        self.session, self.verifier = create_task_state_interfaces(driver)
        self.addCleanup(self.session.stop)

    def test_task_survives_multiple_protocol_operations_and_requires_evidence(self) -> None:
        self.assertEqual(self.session.status(), {"status": "ok", "state": "ready"})
        created = self.session.create_task("task-integration", goal="verify persistent state", constraints=["bounded"], dependencies=[], completion_criteria=["test"])
        rejected = self.session.complete_task("task-integration")
        self.verifier.record_evidence("task-integration", kind="test", status="passed", detail="deterministic integration proof")
        completed = self.session.complete_task("task-integration")
        fetched = self.session.get_task("task-integration")
        self.assertEqual(created["task"]["state"], "open")
        self.assertEqual(rejected["reason"], "verification-evidence-required")
        self.assertEqual(completed["task"]["state"], "completed")
        self.assertEqual(fetched["task"]["state"], "completed")
        self.assertEqual(len(fetched["task"]["evidence"]), 1)

    def test_external_repository_change_invalidates_completed_transition(self) -> None:
        repository = {"root": "/tmp/repo", "head": "h1", "branch": "main"}
        observations = iter((True, False))
        self.session.create_task("task-external-race", goal="reject stale completion", repository=repository, completion_criteria=["test"])
        self.verifier.record_evidence("task-external-race", kind="test", status="passed", detail="verified at h1")
        rejected = self.session.complete_task(
            "task-external-race",
            expected_repository=repository,
            repository_validator=lambda expected: next(observations),
        )
        fetched = self.session.get_task("task-external-race")
        self.assertEqual(rejected, {"status": "rejected", "reason": "repository-snapshot-stale"})
        self.assertEqual(fetched["task"]["state"], "open")

    def test_task_completion_requires_all_dependencies_completed(self) -> None:
        self.session.create_task("dependency", goal="complete prerequisite", completion_criteria=["test"])
        self.session.create_task("dependent", goal="wait for prerequisite", dependencies=["dependency"], completion_criteria=["test"])
        self.verifier.record_evidence("dependent", kind="test", status="passed", detail="dependent verifier passed")
        blocked = self.session.complete_task("dependent")
        self.verifier.record_evidence("dependency", kind="test", status="passed", detail="dependency verifier passed")
        self.session.complete_task("dependency")
        completed = self.session.complete_task("dependent")
        self.assertEqual(blocked, {"status": "rejected", "reason": "dependencies-incomplete"})
        self.assertEqual(completed["task"]["state"], "completed")

    def test_missing_dependency_fails_closed_at_completion(self) -> None:
        self.session.create_task("dependent-missing", goal="reject unknown prerequisite", dependencies=["does-not-exist"], completion_criteria=["test"])
        self.verifier.record_evidence("dependent-missing", kind="test", status="passed", detail="dependent verifier passed")
        self.assertEqual(self.session.complete_task("dependent-missing"), {"status": "rejected", "reason": "dependencies-incomplete"})

    def test_failed_only_evidence_cannot_complete_task(self) -> None:
        self.session.create_task("task-failed-evidence", goal="reject false completion", completion_criteria=["test"])
        self.session.record_evidence("task-failed-evidence", kind="test", status="failed", detail="suite failed")
        rejected = self.session.complete_task("task-failed-evidence")
        fetched = self.session.get_task("task-failed-evidence")
        self.assertEqual(rejected, {"status": "rejected", "reason": "passing-verification-required"})
        self.assertEqual(fetched["task"]["state"], "open")

    def test_completed_task_rejects_further_mutation(self) -> None:
        self.session.create_task("task-terminal", goal="freeze terminal state", completion_criteria=["test"])
        self.verifier.record_evidence("task-terminal", kind="test", status="passed", detail="terminal proof")
        completed = self.session.complete_task("task-terminal")
        repeated = self.session.complete_task("task-terminal")
        mutation = self.session.record_evidence("task-terminal", kind="test", status="failed", detail="late contradictory evidence")
        self.assertEqual(completed["task"]["state"], "completed")
        self.assertEqual(repeated, {"status": "rejected", "reason": "task-already-completed"})
        self.assertEqual(mutation, {"status": "rejected", "reason": "task-already-completed"})

    def test_session_rejects_more_than_64_tasks(self) -> None:
        for index in range(64):
            self.assertEqual(self.session.create_task(f"task-{index}", goal="bounded task", completion_criteria=["verified"])["status"], "ok")
        self.assertEqual(self.session.create_task("task-overflow", goal="must be rejected", completion_criteria=["verified"]), {"status": "rejected", "reason": "task-limit-reached"})

    def test_task_rejects_more_than_64_evidence_records(self) -> None:
        self.session.create_task("task-evidence", goal="bound evidence", completion_criteria=["test"])
        for index in range(64):
            self.assertEqual(self.verifier.record_evidence("task-evidence", kind="test", status="passed", detail=f"proof-{index}")["status"], "ok")
        self.assertEqual(self.verifier.record_evidence("task-evidence", kind="test", status="passed", detail="overflow"), {"status": "rejected", "reason": "evidence-limit-reached"})


if __name__ == "__main__":
    unittest.main()
