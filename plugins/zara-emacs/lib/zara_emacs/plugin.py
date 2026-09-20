"""Zara service plugin for bounded Emacs operations."""

from __future__ import annotations

import json

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .config import EmacsConfig
from .workflow import WorkflowEmacsClient, load_workflows


PLUGIN_VERSION = "0.3.0"


class ZaraEmacsPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-emacs",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Structured Emacs, full Org-roam/Org QL knowledge graph, shared memory, inventory, and Magit integration",
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
            (self.command_catalog, "emacs.command_catalog", "List configuration-owned Emacs action IDs and their exact command symbols for Zara and voice routing."),
            (self.invoke_command, "emacs.invoke_command", "Invoke one configured Emacs action by stable action ID; arbitrary Elisp and raw command names are not accepted."),
            (self.open_scratch, "emacs.open_scratch", "Open the Emacs scratch buffer using the configured server."),
            (self.open_file, "emacs.open_file", "Open an absolute file path in the configured Emacs server."),
            (self.open_buffer, "emacs.open_buffer", "Switch to a named Emacs buffer without arbitrary Elisp."),
            (self.open_daily, "org_roam.open_daily", "Open an Org-roam daily note and request a separate Zara dictation handoff."),
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

    def command_catalog(self) -> str:
        return self._json(self._client.command_catalog())

    def invoke_command(self, action_id: str) -> str:
        return self._json(self._client.invoke_command(action_id))

    def open_scratch(self) -> str:
        return self._json(self._client.open_scratch())

    def open_file(self, path: str) -> str:
        return self._json(self._client.open_file(path))

    def open_buffer(self, name: str) -> str:
        return self._json(self._client.open_buffer(name))

    def open_daily(self, date: str = "today") -> str:
        return self._json(self._client.open_daily(date))

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
