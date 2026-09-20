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
from .language_family import (
    descriptors as language_descriptors,
    invoke_language_operation,
    language_expert_schemas,
    register_descriptor_symbols as register_language_descriptor_symbols,
    register_language_family,
)
from .language_handler import make_language_expert_handler
from .language_source_contract import validate_language_source_contracts
from .lisp_family import (
    descriptors as lisp_descriptors,
    invoke_lisp_operation,
    make_lisp_expert_handler,
    register_descriptor_symbols as register_lisp_descriptor_symbols,
    register_lisp_family,
)


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
        self._registered_lisp_experts: frozenset[str] = frozenset()
        self._registered_language_experts: frozenset[str] = frozenset()

    @staticmethod
    def _plugin_section(configuration: Mapping[str, Any] | object) -> Mapping[str, Any]:
        if not isinstance(configuration, Mapping):
            return {}
        plugins = configuration.get("plugins")
        if isinstance(plugins, Mapping):
            candidate = plugins.get("zara-expert")
            if isinstance(candidate, Mapping):
                return candidate
        return configuration

    @classmethod
    def _lisp_sources(cls, configuration: Mapping[str, Any] | object) -> Mapping[str, Iterable[str | Path]]:
        section = cls._plugin_section(configuration)
        sources = section.get("lisp_family_sources", {})
        if sources is None:
            return {}
        if not isinstance(sources, Mapping):
            raise ExpertError("lisp_family_sources must be a mapping")
        return sources

    @classmethod
    def _language_sources(cls, configuration: Mapping[str, Any] | object) -> Mapping[str, Iterable[str | Path]]:
        section = cls._plugin_section(configuration)
        sources = section.get("language_expert_sources", {})
        if sources is None:
            return {}
        if not isinstance(sources, Mapping):
            raise ExpertError("language_expert_sources must be a mapping")
        return sources

    def start(self, runtime) -> None:
        lisp_sources = self._lisp_sources(runtime.configuration)
        language_sources = self._language_sources(runtime.configuration)

        # Validate the strict pure-symbolic language ABI before mutating any
        # expert namespace. A bad Prolog/Python/Nim brain must not leave an
        # unrelated Lisp family partially active after startup fails.
        validate_language_source_contracts(language_sources)

        self._registered_lisp_experts = register_lisp_family(
            self.host,
            lisp_sources,
        )
        self._registered_language_experts = register_language_family(
            self.host,
            language_sources,
        )
        register_lisp_descriptor_symbols(runtime, self._registered_lisp_experts)
        register_language_descriptor_symbols(runtime, self._registered_language_experts)

    def stop(self) -> None:
        self._registered_lisp_experts = frozenset()
        self._registered_language_experts = frozenset()

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
                "language_family": sorted(self._registered_language_experts),
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
        """Internal/status projection; public discovery is canonical ZARA-EXPERT/1."""
        return self._json(lisp_descriptors(self._registered_lisp_experts))

    def lisp_expert_handler(self, expert_id: str):
        """Return the trusted handler Core binds to one ZARA-EXPERT/1 descriptor.

        The handler accepts Core-owned ``expert_operation`` metadata and emits an
        explicit ``usage.model_calls=0`` ledger. It is intentionally not exposed
        as a StructuredTool, so callers cannot bypass activation, generation,
        cancellation, budget, approval or effect fencing.
        """

        return make_lisp_expert_handler(self.host, expert_id)

    def invoke_lisp_expert(
        self,
        expert_id: str,
        operation: str,
        arguments: list[Any] | None = None,
    ) -> str:
        """Legacy trusted adapter entrypoint for plugin-internal composition.

        This is deliberately not exported as a plugin StructuredTool. New Core
        registration must use :meth:`lisp_expert_handler` so the selected
        operation remains host-owned ZARA-EXPERT/1 metadata.
        """
        return self._json(
            invoke_lisp_operation(self.host, expert_id, operation, arguments)
        )

    def language_family_descriptors(self) -> str:
        """Internal/status projection; public discovery is canonical ZARA-EXPERT/1."""
        return self._json(language_descriptors(self._registered_language_experts))

    def language_family_schemas(self) -> str:
        """Internal schema projection consumed by canonical expert adapter wiring."""
        return self._json(language_expert_schemas())

    def language_expert_handler(self, expert_id: str):
        """Return the trusted Core handler for one language expert descriptor.

        The returned callable accepts host-owned ``expert_operation`` metadata,
        emits an exact zero-model usage ledger, and never exposes a parallel
        StructuredTool that could bypass Core lifecycle or effect fencing.
        """

        return make_language_expert_handler(self.host, expert_id)

    def invoke_language_expert(
        self,
        expert_id: str,
        operation: str,
        arguments: list[Any] | None = None,
    ) -> str:
        """Legacy trusted adapter entrypoint for plugin-internal composition.

        This is deliberately not exported as a plugin StructuredTool. New Core
        registration must use :meth:`language_expert_handler` so the selected
        operation remains host-owned ZARA-EXPERT/1 metadata.
        """
        return self._json(
            invoke_language_operation(self.host, expert_id, operation, arguments)
        )

    def assert_fact(self, namespace: str, fact: str, persistent: bool = False) -> str:
        changed = self.host.assert_fact(namespace, fact, persistent=persistent)
        return self._json({"ok": True, "changed": changed, "persistent": persistent})

    def retract_fact(self, namespace: str, fact: str, persistent: bool = False) -> str:
        changed = self.host.retract_fact(namespace, fact, persistent=persistent)
        return self._json({"ok": True, "changed": changed, "persistent": persistent})

    def tools(self):
        # Expert-family discovery/invocation intentionally does not get a parallel
        # tool namespace. The descriptors published at start() are consumed by
        # Zara's canonical ZARA-EXPERT/1 registry/lifecycle owner.
        return (
            StructuredTool.from_function(func=self.status, name="expert.status", description="Report whether a bounded Prolog backend is available."),
            StructuredTool.from_function(func=self.query, name="expert.query", description="Query one registered expert predicate using structured inert arguments."),
            StructuredTool.from_function(func=self.explain, name="expert.explain", description="Explain one registered expert predicate using the same bounded authority path."),
            StructuredTool.from_function(func=self.assert_fact, name="expert.assert_fact", description="Assert one safe ground fact into session or persistent namespace state."),
            StructuredTool.from_function(func=self.retract_fact, name="expert.retract_fact", description="Idempotently retract one safe ground fact from session or persistent namespace state."),
        )


def create_plugin():
    return ZaraExpertPlugin()
