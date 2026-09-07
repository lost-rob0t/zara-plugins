from __future__ import annotations

import json
import shutil
from collections.abc import Mapping, Sequence
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
                description="Complete one symbolic coding task only when every declared verifier key has current verifier-owned passing evidence and the repository still matches the task snapshot.",
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
        repository_path: str,
        constraints: list[str] | None = None,
        dependencies: list[str] | None = None,
        completion_criteria: list[str] | None = None,
    ) -> str:
        if not isinstance(repository_path, str) or not repository_path:
            raise ValueError("repository_path must be a non-empty string")
        inspector = self._require_inspector()
        observed = inspector.inspect(Path(repository_path))
        repository = {
            "root": observed["root"],
            "head": observed["head"],
            "branch": observed["branch"],
        }
        session = self._require_task_state()
        return json.dumps(
            session.create_task(
                task_id,
                goal=goal,
                repository=repository,
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
        session = self._require_task_state()
        task_response = session.get_task(task_id)
        if task_response.get("status") != "ok":
            return json.dumps(task_response, sort_keys=True)

        task = task_response.get("task")
        repository = task.get("repository") if isinstance(task, Mapping) else None
        if not isinstance(repository, Mapping) or set(repository) != {"root", "head", "branch"}:
            return json.dumps(
                {"status": "rejected", "reason": "task-repository-snapshot-unavailable"},
                sort_keys=True,
            )

        expected_repository = {
            "root": repository["root"],
            "head": repository["head"],
            "branch": repository["branch"],
        }
        observed = self._require_inspector().inspect(Path(expected_repository["root"]))
        observed_repository = {
            "root": observed["root"],
            "head": observed["head"],
            "branch": observed["branch"],
        }
        if observed_repository != expected_repository or bool(observed.get("dirty")):
            return json.dumps(
                {
                    "status": "rejected",
                    "reason": "repository-snapshot-stale",
                    "expected_repository": expected_repository,
                    "observed_repository": observed_repository,
                },
                sort_keys=True,
            )

        return json.dumps(session.complete_task(task_id), sort_keys=True)

    def _require_task_state(self) -> TaskStateSession:
        if self.task_state is None:
            raise RuntimeError(f"zara-coding symbolic task state unavailable: {self.task_state_reason}")
        return self.task_state


def create_plugin(*, plugin_root: Path | None = None) -> TaskStateCodingPlugin:
    return TaskStateCodingPlugin(plugin_root=plugin_root)
