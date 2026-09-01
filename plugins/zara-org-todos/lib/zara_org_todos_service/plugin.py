from __future__ import annotations

import json
import threading

from .config import OrgTodosConfig
from .store import ACTIVE_STATES, OrgTodoStore
from .sync import SYNC_SOURCE_COMMIT, SyncError, SyncResult, SyncRunner


GIT_DISABLED_MESSAGE = "Git synchronization is disabled; Org files are authoritative."


class ZaraOrgTodosPlugin:
    def __init__(self) -> None:
        self._config = None
        self._runner = None
        self._store = None
        self._lock = threading.RLock()
        self._last_result = None
        self._last_error = ""

    def start(self, runtime) -> None:
        config = OrgTodosConfig.from_mapping(runtime.configuration)
        self._config = config
        self._runner = SyncRunner(config) if config.git_sync else None
        self._store = OrgTodoStore(config.org_dir)
        if config.auto_sync:
            runtime.start_worker("sync", self._sync_worker)

    def stop(self) -> None:
        pass

    def tools(self):
        from langchain_core.tools import StructuredTool

        return (
            StructuredTool.from_function(
                func=self.list_todos,
                name="org_todos_list",
                description="List active Org-mode todos. Optional statuses is a comma-separated list of Org TODO states.",
            ),
            StructuredTool.from_function(
                func=self.add_todo,
                name="org_todos_add",
                description="Capture a new todo in the Org-mode inbox. Optional Git sync runs only when configured.",
            ),
            StructuredTool.from_function(
                func=self.edit_todo,
                name="org_todos_edit",
                description="Edit an Org-mode todo title by stable ID. Optional Git sync runs only when configured.",
            ),
            StructuredTool.from_function(
                func=self.complete_todo,
                name="org_todos_complete",
                description="Mark an Org-mode todo DONE by stable ID. Optional Git sync runs only when configured.",
            ),
            StructuredTool.from_function(
                func=self.reopen_todo,
                name="org_todos_reopen",
                description="Reopen an Org-mode todo by stable ID. Optional Git sync runs only when configured.",
            ),
            StructuredTool.from_function(
                func=self.search_todos,
                name="org_todos_search",
                description="Search active Org-mode todos by title.",
            ),
            StructuredTool.from_function(
                func=self.schedule_todo,
                name="org_todos_schedule",
                description="Schedule an Org-mode todo by stable ID using YYYY-MM-DD HH:MM. Optional Git sync runs only when configured.",
            ),
            StructuredTool.from_function(
                func=self.sync_now,
                name="org_todos_sync",
                description="Run the optional Git synchronization transport now. Returns disabled status when Git sync is not configured.",
            ),
            StructuredTool.from_function(
                func=self.status,
                name="org_todos_status",
                description="Report the Org todo backend and optional Git synchronization status.",
            ),
        )

    def list_todos(self, statuses: str = "") -> str:
        store = self._require_store()
        selected = tuple(item.strip().upper() for item in statuses.split(",") if item.strip())
        tasks = store.list(selected or ACTIVE_STATES)
        return "\n".join(task.render() for task in tasks) if tasks else "No matching Org todos."

    def add_todo(self, title: str) -> str:
        self._sync_before_mutation()
        store = self._require_store()
        task = store.add(title)
        return self._mutation_result(task.render(), task.path)

    def edit_todo(self, task_id: str, title: str) -> str:
        self._sync_before_mutation()
        store = self._require_store()
        task = store.edit(task_id, title)
        return self._mutation_result(task.render(), task.path)

    def complete_todo(self, task_id: str) -> str:
        self._sync_before_mutation()
        store = self._require_store()
        task = store.complete(task_id)
        return self._mutation_result(task.render(), task.path)

    def reopen_todo(self, task_id: str) -> str:
        self._sync_before_mutation()
        store = self._require_store()
        task = store.reopen(task_id)
        return self._mutation_result(task.render(), task.path)

    def search_todos(self, query: str) -> str:
        store = self._require_store()
        tasks = store.search(query)
        return "\n".join(task.render() for task in tasks) if tasks else "No matching Org todos."

    def schedule_todo(self, task_id: str, schedule: str) -> str:
        self._sync_before_mutation()
        store = self._require_store()
        task = store.schedule(task_id, schedule)
        return self._mutation_result(task.render(), task.path)

    def sync_now(self) -> str:
        if not self._git_sync_enabled():
            return GIT_DISABLED_MESSAGE
        runner = self._require_runner()
        try:
            result = runner.run()
        except SyncError as error:
            self._record_error(error)
            raise
        self._record_success(result)
        return result.summary

    def status(self) -> str:
        with self._lock:
            config = self._config
            result = self._last_result
            error = self._last_error
        payload = {
            "backend": "org-mode",
            "started": config is not None,
            "last_error": error,
        }
        if config is not None:
            payload.update(
                {
                    "org_dir": str(config.org_dir),
                    "git_sync": config.git_sync,
                    "auto_sync": config.auto_sync,
                    "interval_seconds": config.interval_seconds,
                }
            )
            if config.git_sync:
                payload.update(
                    {
                        "repo_dir": str(config.repo_dir),
                        "remote": config.remote,
                        "sync_source_commit": SYNC_SOURCE_COMMIT,
                    }
                )
        if result is not None:
            payload.update(
                {
                    "last_returncode": result.returncode,
                    "last_duration_seconds": round(result.duration_seconds, 3),
                    "last_summary": result.summary,
                }
            )
        return json.dumps(payload, sort_keys=True)

    def _sync_worker(self, stop_event) -> None:
        config = self._config
        if config is None or not config.git_sync:
            return
        while not stop_event.is_set():
            try:
                self.sync_now()
            except SyncError:
                pass
            if stop_event.wait(config.interval_seconds):
                return

    def _sync_before_mutation(self) -> None:
        if self._git_sync_enabled():
            self.sync_now()

    def _mutation_result(self, rendered: str, path) -> str:
        if not self._git_sync_enabled():
            return rendered
        return f"{rendered}\n{self._sync_file(path)}"

    def _sync_file(self, path) -> str:
        runner = self._require_runner()
        try:
            result = runner.run(saved_file=path)
        except SyncError as error:
            self._record_error(error)
            raise
        self._record_success(result)
        return result.summary

    def _git_sync_enabled(self) -> bool:
        with self._lock:
            return bool(self._config is not None and self._config.git_sync)

    def _require_store(self) -> OrgTodoStore:
        with self._lock:
            if self._store is None:
                raise RuntimeError("zara-org-todos has not started")
            return self._store

    def _require_runner(self) -> SyncRunner:
        with self._lock:
            if self._runner is None:
                raise RuntimeError("Git synchronization is not enabled for zara-org-todos")
            return self._runner

    def _record_success(self, result: SyncResult) -> None:
        with self._lock:
            self._last_result = result
            self._last_error = ""

    def _record_error(self, error: Exception) -> None:
        with self._lock:
            self._last_error = str(error)[:8192]


def create_plugin():
    from zara.plugins import PluginMetadata, ServicePlugin

    metadata = PluginMetadata(
        name="zara-org-todos",
        version="0.1.0",
        api_version="1",
        description="Org-mode todo backend with optional Git synchronization.",
    )

    class ZaraOrgTodosService(ZaraOrgTodosPlugin, ServicePlugin):
        pass

    ZaraOrgTodosService.metadata = metadata
    return ZaraOrgTodosService()
