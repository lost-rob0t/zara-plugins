"""Zara service plugin for sourced knowledge retrieval."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .brave import BraveProvider
from .config import KnowledgeConfig
from .core import KnowledgeEngine
from .store import LocalWikiProvider, WikiStore
from .wiki import GateCatalog, WikiManager, custom_specs, parse_gate_ids


PLUGIN_VERSION = "0.2.0"


class ZaraKnowledgePlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-knowledge",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Federated Brave and wiki search with provenance-preserving local wiki imports and gate routing",
    )

    def __init__(self) -> None:
        self._config = KnowledgeConfig()
        self._brave = None
        self._store = WikiStore(self._config.wiki_store_path)
        self._engine = KnowledgeEngine((LocalWikiProvider(self._store),))
        self._wiki = WikiManager(GateCatalog(), self._store)

    def start(self, runtime) -> None:
        self._config = KnowledgeConfig.load(runtime.configuration)
        self._store = WikiStore(self._config.wiki_store_path)
        self._brave = None
        providers: list[Any] = [LocalWikiProvider(self._store)]
        if self._config.brave_api_key:
            self._brave = BraveProvider(
                api_key=self._config.brave_api_key,
                timeout_seconds=self._config.timeout_seconds,
                max_response_bytes=self._config.max_response_bytes,
            )
            providers.insert(0, self._brave)
        self._engine = KnowledgeEngine(providers)
        catalog = GateCatalog(custom=custom_specs(self._config.wiki_gates))
        self._wiki = WikiManager(
            catalog,
            self._store,
            site_search_provider=self._brave,
            max_gates=self._config.wiki_max_gates,
            timeout_seconds=self._config.timeout_seconds,
            max_response_bytes=self._config.max_response_bytes,
        )

    def stop(self) -> None:
        return None

    def tools(self):
        return (
            StructuredTool.from_function(
                func=self.knowledge_search,
                name="knowledge.search",
                description="Federate Brave, imported wiki knowledge, and explicitly selected live wiki gates.",
            ),
            StructuredTool.from_function(
                func=self.knowledge_status,
                name="knowledge.status",
                description="Report web/wiki search availability, gate catalog, and local import state without credentials.",
            ),
            StructuredTool.from_function(
                func=self.wiki_gates,
                name="wiki.gates",
                description="List named wiki gates, Wikimedia language-family templates, and supported wiki engine families.",
            ),
            StructuredTool.from_function(
                func=self.wiki_search,
                name="wiki.search",
                description="Search one or more explicitly selected wiki gates with bounded fan-out and source provenance.",
            ),
            StructuredTool.from_function(
                func=self.wiki_import,
                name="wiki.import",
                description="Import one page from a native wiki gate into Zara's local provenance-preserving wiki store.",
            ),
            StructuredTool.from_function(
                func=self.wiki_local_search,
                name="wiki.local_search",
                description="Search previously imported wiki pages locally without network access.",
            ),
        )

    def knowledge_search(
        self,
        query: str,
        count: int = 5,
        language: str = "",
        safe_search: str = "moderate",
        freshness: str = "",
        gates: str = "",
    ) -> str:
        bounded_count = min(count, self._config.max_results)
        selected = parse_gate_ids(gates) if gates else list(self._config.wiki_default_gates)
        base = self._engine.search(
            query,
            count=bounded_count,
            language=language,
            safe_search=safe_search,
            freshness=freshness,
            gates=selected,
        )
        if self._brave is None:
            base["errors"].append(
                {
                    "provider": "brave",
                    "kind": "unavailable",
                    "message": "Brave Search is not configured",
                }
            )

        if not selected:
            return json.dumps(base, ensure_ascii=False, sort_keys=True)

        live = self._wiki.search(
            query,
            selected,
            count=bounded_count,
            language=language,
            safe_search=safe_search,
            freshness=freshness,
        )
        result = {
            "query": query.strip(),
            "gates": selected,
            "results": _fuse(live["results"], base["results"], bounded_count),
            "errors": [*live["errors"], *base["errors"]],
        }
        return json.dumps(result, ensure_ascii=False, sort_keys=True)

    def knowledge_status(self) -> str:
        return json.dumps(
            {
                "default_provider": self._config.default_provider,
                "providers": {
                    "brave": {
                        "configured": bool(self._config.brave_api_key),
                        "available": self._brave is not None,
                    },
                    "wiki-import": {
                        "configured": True,
                        "available": True,
                        "pages": self._store.count(),
                    },
                },
                "wiki": self._wiki.status(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def wiki_gates(self) -> str:
        return json.dumps(self._wiki.catalog.describe(), ensure_ascii=False, sort_keys=True)

    def wiki_search(self, query: str, gates: str, count: int = 5) -> str:
        selected = parse_gate_ids(gates)
        result = self._wiki.search(query, selected, count=min(count, self._config.max_results))
        return json.dumps(result, ensure_ascii=False, sort_keys=True)

    def wiki_import(self, gate: str, title: str) -> str:
        result = self._wiki.import_page(gate, title)
        return json.dumps(result, ensure_ascii=False, sort_keys=True)

    def wiki_local_search(self, query: str, count: int = 5, gates: str = "") -> str:
        selected = parse_gate_ids(gates)
        result = self._wiki.local_search(
            query,
            count=min(count, self._config.max_results),
            gate_ids=selected,
        )
        return json.dumps(result, ensure_ascii=False, sort_keys=True)


def _fuse(primary: list[dict[str, Any]], secondary: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    queues = [list(primary), list(secondary)]
    while len(result) < limit and any(queues):
        for queue in queues:
            if not queue or len(result) >= limit:
                continue
            item = queue.pop(0)
            identity = (
                str(item.get("gate") or ""),
                str(item.get("provider") or ""),
                str(item.get("url") or ""),
            )
            if identity in seen:
                continue
            seen.add(identity)
            result.append(item)
    return result


def create_plugin():
    return ZaraKnowledgePlugin()
