from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from pathlib import Path

from langchain_core.tools import StructuredTool

from .domain import CodingError
from .plugin import ZaraCodingPlugin
from .task_state import TaskStateSession


class TaskStateCodingPlugin(ZaraCodingPlugin):
    def __init__(self, *, plugin_root: Path | None = None) -> None:
        super().__init__()
        self.plugin_root = (plugin_root or Path(__file__).resolve().parents[2]).resolve()
        self.task_state: TaskStateSession | None = None
        self.task_state_reason = "not-started"

    def start(self, runtime) -> None:
        super().start(runtime)
        section = self._section(runtime.configuration)
        checkout = section.get("prolog_rlm_checkout")
        executable = section.get("swipl", "swipl")
        if not checkout:
            self.task_state = None
            self.task_state_reason = "prolog-rlm-checkout-not-configured"
            return
        if not isinstance(executable, str) or not executable:
            raise ValueError("swipl must be a non-empty string")
        if shutil.which(executable) is None:
            self.task_state = None
            self.task_state_reason = "swipl-executable-not-found"
            return
        driver = self.plugin_root / "prolog" / "zara_coding_task_state.pl"
        if not driver.is_file():
            self.task_state = None
            self.task_state_reason = "task-state-driver-missing"
            return
        session = TaskStateSession(driver, executable=executable)
        try:
            session.start()
            session.status()
        except CodingError:
            session.stop()
            self.task_state = None
            self.task_state_reason = "task-state-prolog-not-ready"
            return
        self.task_state = session
        self.task_state_reason = "ready"

    def stop(self) -> None:
        session = self.task_state
        self.task_state = None
        if session is not None:
            session.stop()
        self.task_state_reason = "stopped"
        super().stop()

    def tools(self) -> Sequence[StructuredTool]:
        return (
            *super().tools(),
            StructuredTool.from_function(
                func=self.task_create,
                name="coding.task.create",
                description="Create bounded Prolog-owned symbolic coding task state with completion criteria.",
            ),
            StructuredTool.from_function(
                func=self.task_get,
                name="coding.task.get",
                description="Read one Prolog-owned symbolic coding task and its verification evidence.",
            ),
            StructuredTool.from_function(
                func=self.task_record_evidence,
                name="coding.task.record-evidence",
                description="Record bounded structured verification evidence against one symbolic coding task.",
            ),
            StructuredTool.from_function(
                func=self.task_complete,
                name="coding.task.complete",
                description="Complete one symbolic coding task only when Prolog state contains verification evidence.",
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
        constraints: list[str] | None = None,
        dependencies: list[str] | None = None,
        completion_criteria: list[str] | None = None,
    ) -> str:
        session = self._require_task_state()
        return json.dumps(
            session.create_task(
                task_id,
                goal=goal,
                constraints=constraints or (),
                dependencies=dependencies or (),
                completion_criteria=completion_criteria or (),
            ),
            sort_keys=True,
        )

    def task_get(self, task_id: str) -> str:
        return json.dumps(self._require_task_state().get_task(task_id), sort_keys=True)

    def task_record_evidence(self, task_id: str, kind: str, status: str, detail: str) -> str:
        return json.dumps(
            self._require_task_state().record_evidence(task_id, kind=kind, status=status, detail=detail),
            sort_keys=True,
        )

    def task_complete(self, task_id: str) -> str:
        return json.dumps(self._require_task_state().complete_task(task_id), sort_keys=True)

    def _require_task_state(self) -> TaskStateSession:
        if self.task_state is None:
            raise RuntimeError(f"zara-coding symbolic task state unavailable: {self.task_state_reason}")
        return self.task_state


def create_plugin(*, plugin_root: Path | None = None) -> TaskStateCodingPlugin:
    return TaskStateCodingPlugin(plugin_root=plugin_root)
