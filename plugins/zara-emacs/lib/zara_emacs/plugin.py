"""Zara service plugin for bounded Emacs operations."""

from __future__ import annotations

import json

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .config import EmacsConfig
from .workflow import WorkflowEmacsClient, load_workflows


PLUGIN_VERSION = "0.4.0"


class ZaraEmacsPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-emacs",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Deep native Emacs bridge with bounded Org TODO, Org-roam, shared-memory, inventory, and Magit operations",
    )

    def __init__(self) -> None:
        config = EmacsConfig()
        self._client = WorkflowEmacsClient(config, workflows={})

    def start(self, runtime) -> None:
        config = EmacsConfig.load(runtime.configuration)
        workflows = load_workflows(runtime.configuration, projects=config.projects)
        self._client = WorkflowEmacsClient(config, workflows=workflows)

    def stop(self) -> None:
        return None

    def tools(self):
        operations = (
            (self.open_scratch, "emacs.open_scratch", "Open the Emacs scratch buffer using the configured server."),
            (self.open_file, "emacs.open_file", "Open an absolute file path in the configured Emacs server."),
            (self.open_buffer, "emacs.open_buffer", "Switch to a named Emacs buffer without arbitrary Elisp."),
            (self.describe_session, "emacs.session_describe", "Describe the live versioned Zara/Emacs bridge and its capabilities."),
            (self.buffers, "emacs.buffers", "List bounded live Emacs buffers with opaque IDs and revision metadata."),
            (self.buffer_context, "emacs.buffer_context", "Read structured live context for the selected or identified Emacs buffer."),
            (self.read_buffer, "emacs.read_buffer", "Read a bounded range from a live Emacs buffer by opaque ID."),
            (self.preview_edit, "emacs.preview_edit", "Preview a revision-checked atomic Emacs edit without applying or saving it."),
            (self.apply_edit, "emacs.apply_edit", "Apply a previously previewed Emacs edit if the captured revision is still current."),
            (self.cancel_edit, "emacs.cancel_edit", "Cancel a pending Emacs edit preview."),
            (self.edit_status, "emacs.edit_status", "Inspect the state of an Emacs edit receipt."),
            (self.save_buffer, "emacs.save_buffer", "Explicitly save an identified Emacs buffer after separate edit application."),
            (self.windows, "emacs.windows", "List live windows in the selected Emacs frame with opaque IDs."),
            (self.select_window, "emacs.select_window", "Select a live Emacs window by opaque ID."),
            (self.split_window, "emacs.split_window", "Split an identified Emacs window below or right."),
            (self.delete_window, "emacs.delete_window", "Delete an identified Emacs window using native Emacs semantics."),
            (self.commands, "emacs.commands", "Search bounded live interactive Emacs commands."),
            (self.describe_command, "emacs.describe_command", "Describe a live interactive Emacs command and its effective keys."),
            (self.where_is, "emacs.where_is", "Report live key bindings for an Emacs command."),
            (self.key_lookup, "emacs.key_lookup", "Resolve an effective Emacs key sequence in the current buffer."),
            (self.open_daily, "org_roam.open_daily", "Open an Org-roam daily note and request a separate Zara dictation handoff."),
            (self.todo_list, "org_todo.list", "List bounded canonical Org TODOs through the trusted Emacs adapter."),
            (self.todo_capture, "org_todo.capture", "Capture a canonical Org TODO with an optional bounded scheduled timestamp."),
            (self.todo_state, "org_todo.state", "Change one canonical Org TODO state by stable Org ID."),
            (self.todo_snapshot, "org_todo.snapshot", "Refresh the derived Prolog projection of canonical Org TODO state."),
            (self.roam_search, "org_roam.search", "Search bounded Org-roam nodes through the trusted Emacs adapter."),
            (self.shared_memory, "org_ql.shared_memory", "Query bounded active shared agent-memory assertions from the full Org graph."),
            (self.inventory, "org_ql.inventory", "Query bounded inventory, food, and stock-event entities from the full Org graph."),
            (self.unresolved_inventory, "inventory.unresolved", "List inventory events that still need a stable Org-roam item ID."),
            (self.materialize_inventory_item, "inventory.materialize_item", "Create or resolve a stable Org-roam inventory-item node from an item key."),
            (self.record_inventory_event, "inventory.record_event", "Append a structured inventory event to an Org-roam daily page."),
            (self.append_shared_memory, "org_memory.append_shared", "Append a provenance-bearing shared-memory Org-roam assertion and optionally supersede a prior assertion."),
            (self.open_magit, "magit.open_project", "Open Magit for a configured project alias."),
            (self.open_dashboard, "emacs.open_dashboard", "Open the typed AI dashboard using a fixed Emacs template."),
            (self.open_zara_chat, "emacs.open_zara_chat", "Open the native Zara Emacs chat using a fixed template."),
            (self.run_workflow, "emacs.run_workflow", "Run a named configuration-owned Emacs workflow."),
            (self.context, "emacs.context", "Read bounded current Emacs buffer, file, and project context."),
        )
        return tuple(
            StructuredTool.from_function(func=func, name=name, description=description)
            for func, name, description in operations
        )

    @staticmethod
    def _json(value) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def open_scratch(self) -> str:
        return self._json(self._client.open_scratch())

    def open_file(self, path: str) -> str:
        return self._json(self._client.open_file(path))

    def open_buffer(self, name: str) -> str:
        return self._json(self._client.open_buffer(name))

    def describe_session(self) -> str:
        return self._json(self._client.describe_session())

    def buffers(self, limit: int = 100) -> str:
        return self._json(self._client.buffers(limit))

    def buffer_context(self, buffer_id: str = "") -> str:
        return self._json(self._client.buffer_context(buffer_id))

    def read_buffer(
        self,
        buffer_id: str,
        start: int | None = None,
        end: int | None = None,
    ) -> str:
        return self._json(self._client.read_buffer(buffer_id, start, end))

    def preview_edit(
        self,
        buffer_id: str,
        start: int,
        end: int,
        expected_tick: int,
        replacement: str,
    ) -> str:
        return self._json(
            self._client.preview_edit(
                buffer_id,
                start,
                end,
                expected_tick,
                replacement,
            )
        )

    def apply_edit(self, edit_id: str) -> str:
        return self._json(self._client.apply_edit(edit_id))

    def cancel_edit(self, edit_id: str) -> str:
        return self._json(self._client.cancel_edit(edit_id))

    def edit_status(self, edit_id: str) -> str:
        return self._json(self._client.edit_status(edit_id))

    def save_buffer(self, buffer_id: str) -> str:
        return self._json(self._client.save_buffer(buffer_id))

    def windows(self) -> str:
        return self._json(self._client.windows())

    def select_window(self, window_id: str) -> str:
        return self._json(self._client.select_window(window_id))

    def split_window(
        self,
        window_id: str,
        side: str = "below",
        size: int | None = None,
    ) -> str:
        return self._json(self._client.split_window(window_id, side, size))

    def delete_window(self, window_id: str) -> str:
        return self._json(self._client.delete_window(window_id))

    def commands(self, query: str = "", limit: int = 100) -> str:
        return self._json(self._client.commands(query, limit))

    def describe_command(self, command: str) -> str:
        return self._json(self._client.describe_command(command))

    def where_is(self, command: str) -> str:
        return self._json(self._client.where_is(command))

    def key_lookup(self, key: str) -> str:
        return self._json(self._client.key_lookup(key))

    def open_daily(self, date: str = "today") -> str:
        return self._json(self._client.open_daily(date))

    def todo_list(self, state: str = "active", limit: int = 100) -> str:
        return self._json(self._client.todo_list(state, limit))

    def todo_capture(self, title: str, scheduled: str = "") -> str:
        return self._json(self._client.todo_capture(title, scheduled))

    def todo_state(self, todo_id: str, state: str) -> str:
        return self._json(self._client.todo_state(todo_id, state))

    def todo_snapshot(self) -> str:
        return self._json(self._client.todo_snapshot())

    def roam_search(self, query: str, limit: int = 50) -> str:
        return self._json(self._client.roam_search(query, limit))

    def shared_memory(self, limit: int = 100) -> str:
        return self._json(self._client.shared_memory(limit))

    def inventory(self, limit: int = 100) -> str:
        return self._json(self._client.inventory(limit))

    def unresolved_inventory(self, limit: int = 100) -> str:
        return self._json(self._client.unresolved_inventory(limit))

    def materialize_inventory_item(
        self,
        item_key: str,
        name: str,
        unit: str,
        source: str,
        category: str = "",
        barcode: str = "",
        sku: str = "",
        default_location: str = "",
        reorder_at: float | None = None,
    ) -> str:
        return self._json(
            self._client.materialize_inventory_item(
                item_key,
                name,
                unit,
                source,
                category,
                barcode,
                sku,
                default_location,
                reorder_at,
            )
        )

    def record_inventory_event(
        self,
        event: str,
        item_key: str,
        qty: float,
        unit: str,
        source: str,
        item_id: str = "",
        from_location: str = "",
        to_location: str = "",
        day: str = "today",
        adjustment: str = "",
    ) -> str:
        return self._json(
            self._client.record_inventory_event(
                event,
                item_key,
                qty,
                unit,
                source,
                item_id,
                from_location,
                to_location,
                day,
                adjustment,
            )
        )

    def append_shared_memory(
        self,
        subject: str,
        value: str,
        author: str,
        source: str,
        supersedes: str = "",
    ) -> str:
        return self._json(
            self._client.append_shared_memory(
                subject,
                value,
                author,
                source,
                supersedes,
            )
        )

    def open_magit(self, project_id: str) -> str:
        return self._json(self._client.open_magit(project_id))

    def open_dashboard(self) -> str:
        return self._json(self._client.open_dashboard())

    def open_zara_chat(self) -> str:
        return self._json(self._client.open_zara_chat())

    def run_workflow(self, workflow_id: str) -> str:
        return self._json(self._client.run_workflow(workflow_id))

    def context(self) -> str:
        return self._json(self._client.context())


def create_plugin():
    return ZaraEmacsPlugin()
