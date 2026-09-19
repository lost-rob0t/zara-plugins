"""Zara service plugin for bounded Emacs operations."""

from __future__ import annotations

import json

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .client import EmacsClient
from .config import EmacsConfig


PLUGIN_VERSION = "0.2.0"


class ZaraEmacsPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-emacs",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Structured Emacs, Org-roam daily, and Magit project integration",
    )

    def __init__(self) -> None:
        self._client = EmacsClient(EmacsConfig())

    def start(self, runtime) -> None:
        self._client = EmacsClient(EmacsConfig.load(runtime.configuration))

    def stop(self) -> None:
        return None

    def tools(self):
        operations = (
            (self.open_scratch, "emacs.open_scratch", "Open the Emacs scratch buffer using the configured server."),
            (self.open_file, "emacs.open_file", "Open an absolute file path in the configured Emacs server."),
            (self.open_buffer, "emacs.open_buffer", "Switch to a named Emacs buffer without arbitrary Elisp."),
            (self.open_daily, "org_roam.open_daily", "Open an Org-roam daily note and request a separate Zara dictation handoff."),
            (self.shared_memory, "org_ql.shared_memory", "Query bounded active shared agent-memory assertions from the full Org graph."),
            (self.inventory, "org_ql.inventory", "Query bounded inventory, food, and stock-event entities from the full Org graph."),
            (self.record_inventory_event, "inventory.record_event", "Append a structured inventory event to an Org-roam daily page."),
            (self.append_shared_memory, "org_memory.append_shared", "Append a provenance-bearing shared-memory Org-roam assertion and optionally supersede a prior assertion."),
            (self.open_magit, "magit.open_project", "Open Magit for a configured project alias."),
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

    def open_daily(self, date: str = "today") -> str:
        return self._json(self._client.open_daily(date))

    def shared_memory(self, limit: int = 100) -> str:
        return self._json(self._client.shared_memory(limit))

    def inventory(self, limit: int = 100) -> str:
        return self._json(self._client.inventory(limit))

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

    def context(self) -> str:
        return self._json(self._client.context())


def create_plugin():
    return ZaraEmacsPlugin()
