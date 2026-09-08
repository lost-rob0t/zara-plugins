from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .backend import SwiplBackend
from .domain import ExpertError, ExpertHost


PLUGIN_VERSION = "0.1.0"


class UnavailableExpertBackend:
    reason = "swipl-backend-unavailable"

    def run(self, request):
        raise ExpertError(self.reason)


class ZaraExpertPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-expert",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Isolated bounded Prolog expert-system host for Zara plugins",
    )

    def __init__(self, backend=None, state_root: Path | None = None) -> None:
        data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        root = Path(state_root) if state_root is not None else data_home / "zarathushtra" / "zara-expert"
        if backend is None:
            backend = SwiplBackend() if SwiplBackend.available() else UnavailableExpertBackend()
        self.backend = backend
        self.host = ExpertHost(self.backend, state_root=root)

    def start(self, runtime) -> None:
        return None

    def stop(self) -> None:
        return None

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def status(self) -> str:
        if isinstance(self.backend, UnavailableExpertBackend):
            return self._json({"status": "unavailable", "reason": self.backend.reason})
        return self._json({"status": "ready", "backend": "swipl" if isinstance(self.backend, SwiplBackend) else "custom"})

    def register_namespace(
        self,
        namespace: str,
        knowledge_bases: Iterable[Path],
        predicates: Mapping[str, int],
    ) -> None:
        """Trusted construction-time registration; intentionally not a StructuredTool."""
        self.host.register(namespace, knowledge_bases, predicates=predicates)

    def query(self, namespace: str, predicate: str, arguments: list[Any] | None = None) -> str:
        return self._json(self.host.query(namespace, predicate, arguments))

    def explain(self, namespace: str, predicate: str, arguments: list[Any] | None = None) -> str:
        return self._json(self.host.explain(namespace, predicate, arguments))

    def assert_fact(self, namespace: str, fact: str, persistent: bool = False) -> str:
        changed = self.host.assert_fact(namespace, fact, persistent=persistent)
        return self._json({"ok": True, "changed": changed, "persistent": persistent})

    def retract_fact(self, namespace: str, fact: str, persistent: bool = False) -> str:
        changed = self.host.retract_fact(namespace, fact, persistent=persistent)
        return self._json({"ok": True, "changed": changed, "persistent": persistent})

    def tools(self):
        return (
            StructuredTool.from_function(func=self.status, name="expert.status", description="Report whether a bounded Prolog backend is available."),
            StructuredTool.from_function(func=self.query, name="expert.query", description="Query one registered expert predicate using structured inert arguments."),
            StructuredTool.from_function(func=self.explain, name="expert.explain", description="Explain one registered expert predicate using the same bounded authority path."),
            StructuredTool.from_function(func=self.assert_fact, name="expert.assert_fact", description="Assert one safe ground fact into session or persistent namespace state."),
            StructuredTool.from_function(func=self.retract_fact, name="expert.retract_fact", description="Idempotently retract one safe ground fact from session or persistent namespace state."),
        )


def create_plugin():
    return ZaraExpertPlugin()
