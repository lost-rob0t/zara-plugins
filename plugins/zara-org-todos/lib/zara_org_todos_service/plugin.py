from __future__ import annotations

import json
import threading

from .config import OrgTodosConfig
from .store import ACTIVE_STATES, OrgTodoStore
from .sync import SYNC_SOURCE_COMMIT, SyncError, SyncResult, SyncRunner


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
        self._runner = SyncRunner(config)
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
                description="Capture a new todo in the Org-mode inbox and synchronize it.",
            ),
            StructuredTool.from_function(
                func=self.edit_todo,
                name="org_todos_edit",
                description="Edit an Org-mode todo title by stable ID and synchronize it.",
            ),
            StructuredTool.from_function(
                func=self.complete_todo,
                name="org_todos_complete",
                description="Mark an Org-mode todo DONE by stable ID and synchronize it.",
            ),
            StructuredTool.from_function(
                func=self.reopen_todo,
                name="org_todos_reopen",
                description="Reopen an Org-mode todo by stable ID and synchronize it.",
            ),
            StructuredTool.from_function(
                func=self.search_todos,
                name="org_todos_search",
                description="Search active Org-mode todos by title.",
            ),
            StructuredTool.from_function(
                func=self.schedule_todo,
                name="org_todos_schedule",
                description="Schedule an Org-mode todo by stable ID using YYYY-MM-DD HH:MM and synchronize it.",
            ),
            StructuredTool.from_function(
                func=self.sync_now,
                name="org_todos_sync",
                description="Synchronize the Org-mode todo agenda with its durable Git remote now.",
            ),
            StructuredTool.from_function(
                func=self.status,
                name="org_todos_status",
                description="Report the configured Org todo backend and the most recent sync result.",
            ),
        )

    def list_todos(self, statuses: str = "") -> str:
        store = self._require_store()
        selected = tuple(item.strip().upper() for item in statuses.split(",") if item.strip())
        tasks = store.list(selected or ACTIVE_STATES)
        return "\n".join(task.render() for task in tasks) if tasks else "No matching Org todos."

    def add_todo(self, title: str) -> str:
        self.sync_now()
        store = self._require_store()
        task = store.add(title)
        sync = self._sync_file(task.path)
        return f"{task.render()}\n{sync}"

    def edit_todo(self, task_id: str, title: str) -> str:
        self.sync_now()
        store = self._require_store()
        task = store.edit(task_id, title)
        sync = self._sync_file(task.path)
        return f"{task.render()}\n{sync}"

    def complete_todo(self, task_id: str) -> str:
        self.sync_now()
        store = self._require_store()
        task = store.complete(task_id)
        sync = self._sync_file(task.path)
        return f"{task.render()}\n{sync}"

    def reopen_todo(self, task_id: str) -> str:
        self.sync_now()
        store = self._require_store()
        task = store.reopen(task_id)
        sync = self._sync_file(task.path)
        return f"{task.render()}\n{sync}"

    def search_todos(self, query: str) -> str:
        store = self._require_store()
        tasks = store.search(query)
        return "\n".join(task.render() for task in tasks) if tasks else "No matching Org todos."

    def schedule_todo(self, task_id: str, schedule: str) -> str:
        self.sync_now()
        store = self._require_store()
        task = store.schedule(task_id, schedule)
        sync = self._sync_file(task.path)
        return f"{task.render()}\n{sync}"

    def sync_now(self) -> str:
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
            "sync_source_commit": SYNC_SOURCE_COMMIT,
            "started": config is not None,
            "last_error": error,
        }
        if config is not None:
            payload.update(
                {
                    "repo_dir": str(config.repo_dir),
                    "org_dir": str(config.org_dir),
                    "remote": config.remote,
                    "auto_sync": config.auto_sync,
                    "interval_seconds": config.interval_seconds,
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
        if config is None:
            return
        while not stop_event.is_set():
            try:
                self.sync_now()
            except SyncError:
                pass
            if stop_event.wait(config.interval_seconds):
                return

    def _sync_file(self, path) -> str:
        runner = self._require_runner()
        try:
            result = runner.run(saved_file=path)
        except SyncError as error:
            self._record_error(error)
            raise
        self._record_success(result)
        return result.summary

    def _require_store(self) -> OrgTodoStore:
        with self._lock:
            if self._store is None:
                raise RuntimeError("zara-org-todos has not started")
            return self._store

    def _require_runner(self) -> SyncRunner:
        with self._lock:
            if self._runner is None:
                raise RuntimeError("zara-org-todos has not started")
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
        description="Org-mode todo backend with durable Git synchronization.",
    )

    class ZaraOrgTodosService(ZaraOrgTodosPlugin, ServicePlugin):
        pass

    ZaraOrgTodosService.metadata = metadata
    return ZaraOrgTodosService()
