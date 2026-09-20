from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Iterable

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .backend import SwiplBackend
from .domain import ExpertError, ExpertHost
from .lisp_family import (
    descriptors as lisp_descriptors,
    invoke_lisp_operation,
    register_descriptor_symbols,
    register_lisp_family,
)


PLUGIN_VERSION = "0.2.0"


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
        self._registered_lisp_experts: frozenset[str] = frozenset()

    @staticmethod
    def _lisp_sources(configuration: Mapping[str, Any] | object) -> Mapping[str, Iterable[str | Path]]:
        if not isinstance(configuration, Mapping):
            return {}
        section: Mapping[str, Any] = configuration
        plugins = configuration.get("plugins")
        if isinstance(plugins, Mapping):
            candidate = plugins.get("zara-expert")
            if isinstance(candidate, Mapping):
                section = candidate
        sources = section.get("lisp_family_sources", {})
        if sources is None:
            return {}
        if not isinstance(sources, Mapping):
            raise ExpertError("lisp_family_sources must be a mapping")
        return sources

    def start(self, runtime) -> None:
        self._registered_lisp_experts = register_lisp_family(
            self.host,
            self._lisp_sources(runtime.configuration),
        )
        register_descriptor_symbols(runtime, self._registered_lisp_experts)

    def stop(self) -> None:
        self._registered_lisp_experts = frozenset()

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def status(self) -> str:
        if isinstance(self.backend, UnavailableExpertBackend):
            return self._json({"status": "unavailable", "reason": self.backend.reason})
        return self._json(
            {
                "status": "ready",
                "backend": "swipl" if isinstance(self.backend, SwiplBackend) else "custom",
                "lisp_family": sorted(self._registered_lisp_experts),
                "model_calls": 0,
            }
        )

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

    def lisp_family_descriptors(self) -> str:
        return self._json(lisp_descriptors(self._registered_lisp_experts))

    def invoke_lisp_expert(
        self,
        expert_id: str,
        operation: str,
        arguments: list[Any] | None = None,
    ) -> str:
        return self._json(
            invoke_lisp_operation(self.host, expert_id, operation, arguments)
        )

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
            StructuredTool.from_function(func=self.lisp_family_descriptors, name="expert.lisp_descriptors", description="List deterministic ZARA-EXPERT/1 Lisp-family descriptors and availability."),
            StructuredTool.from_function(func=self.invoke_lisp_expert, name="expert.lisp_invoke", description="Invoke a fixed Lisp-family symbolic operation through registered predicate authority; never performs provider/model fallback."),
            StructuredTool.from_function(func=self.assert_fact, name="expert.assert_fact", description="Assert one safe ground fact into session or persistent namespace state."),
            StructuredTool.from_function(func=self.retract_fact, name="expert.retract_fact", description="Idempotently retract one safe ground fact from session or persistent namespace state."),
        )


def create_plugin():
    return ZaraExpertPlugin()
