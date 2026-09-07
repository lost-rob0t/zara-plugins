from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from langchain_core.tools import StructuredTool

from .coding import CodingError, ZaraCodingPlugin
from .task_state import TaskStateSession


class TaskStateCodingPlugin(ZaraCodingPlugin):
    def __init__(self, *, task_state: TaskStateSession | None = None) -> None:
        super().__init__()
        self.task_state = task_state
        self.task_state_reason = "task-state-not-started"

    def start(self, runtime) -> None:
        super().start(runtime)
        if self.task_state is not None:
            self.task_state_reason = ""
            return
        try:
            self.task_state = TaskStateSession(
                Path(__file__).resolve().parents[2] / "prolog" / "zara_coding_task_state.pl"
            )
            self.task_state.status()
            self.task_state_reason = ""
        except Exception as exc:
            self.task_state = None
            self.task_state_reason = str(exc)

    def stop(self) -> None:
        if self.task_state is not None:
            self.task_state.stop()
            self.task_state = None
        super().stop()

    def tools(self) -> Sequence[StructuredTool]:
        return (
            *super().tools(),
            StructuredTool.from_function(
                func=self.task_create,
                name="coding.task.create",
                description="Create bounded Prolog-owned symbolic coding task state. Each completion criterion is a verifier key that requires its own current verifier-owned passing evidence.",
            ),
            StructuredTool.from_function(
                func=self.task_get,
                name="coding.task.get",
                description="Read one Prolog-owned symbolic coding task and its verification evidence.",
            ),
            StructuredTool.from_function(
                func=self.task_record_evidence,
                name="coding.task.record-evidence",
                description="Record bounded caller-authored failed observations. Passing evidence is verifier-owned and cannot be caller-authored through this public tool.",
            ),
            StructuredTool.from_function(
                func=self.task_complete,
                name="coding.task.complete",
                description="Complete one symbolic coding task only when every declared verifier key has current verifier-owned passing evidence.",
            ),
        )

    def status(self) -> str:
        state = json.loads(super().status())
        state["task_state"] = (
            {"status": "ready"}
            if self.task_state is not None
            else {"status": "unavailable", "reason": self.task_state_reason}
        )
        if state["task_state"]["status"] != "ready":
            state["status"] = "degraded"
        return json.dumps(state, sort_keys=True)

    def task_create(
        self,
        task_id: str,
        goal: str,
        repository: str | None = None,
        constraints: list[str] | None = None,
        dependencies: list[str] | None = None,
        completion_criteria: list[str] | None = None,
    ) -> str:
        repository_identity = None
        if repository is not None:
            repository_identity = json.loads(self.repo_inspect(repository))
        return json.dumps(
            self._require_task_state().create_task(
                task_id,
                goal=goal,
                repository=repository_identity,
                constraints=constraints or (),
                dependencies=dependencies or (),
                completion_criteria=completion_criteria or (),
            ),
            sort_keys=True,
        )

    def task_get(self, task_id: str) -> str:
        return json.dumps(self._require_task_state().get_task(task_id), sort_keys=True)

    def task_record_evidence(self, task_id: str, kind: str, status: str, detail: str) -> str:
        if status == "passed":
            raise ValueError("passing task evidence is verifier-owned")
        return json.dumps(
            self._require_task_state().record_evidence(
                task_id,
                kind=kind,
                status=status,
                detail=detail,
                provenance="caller",
            ),
            sort_keys=True,
        )

    def task_complete(self, task_id: str) -> str:
        return json.dumps(self._require_task_state().complete_task(task_id), sort_keys=True)

    def _require_task_state(self) -> TaskStateSession:
        if self.task_state is None:
            raise CodingError(f"zara-coding symbolic task state unavailable: {self.task_state_reason}")
        return self.task_state
