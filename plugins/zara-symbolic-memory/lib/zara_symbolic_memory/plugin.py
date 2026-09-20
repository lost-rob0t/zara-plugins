from __future__ import annotations

import json
import os
from pathlib import Path

from .embedding import OllamaEmbedder, OpenAICompatibleEmbedder
from .prolog import PrologQueryEngine
from .store import SymbolicMemoryError, SymbolicMemoryStore


PLUGIN_NAME = "zara-symbolic-memory"
PLUGIN_VERSION = "0.1.0"
PLUGIN_DESCRIPTION = "Prolog-authoritative symbolic memory with Prolog-resident embedding indexes and query rules"


class ZaraSymbolicMemoryPlugin:
    def __init__(self) -> None:
        self.store: SymbolicMemoryStore | None = None
        self.engine: PrologQueryEngine | None = None
        self.kb_roots: tuple[str, ...] = ()
        self._tools = None

    def start(self, runtime):
        configuration = dict(runtime.configuration)
        data_dir = configuration.get("data_dir") or os.getenv("ZARA_SYMBOLIC_MEMORY_DIR")
        if not data_dir:
            data_root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
            data_dir = str(data_root / "zara" / "symbolic-memory")
        embedder = self._build_embedder(configuration)
        self.kb_roots = tuple(str(value) for value in configuration.get("kb_roots", ()) if str(value).strip())
        self.store = SymbolicMemoryStore(data_dir, embedder=embedder)
        rules_path = Path(__file__).resolve().parents[2] / "prolog" / "query_rules.pl"
        self.engine = PrologQueryEngine(self.store, rules_path, embedder=embedder)
        self._tools = None
        if configuration.get("require_prolog", True) and not self.engine.ready():
            try:
                from zara.plugins import StartupUnavailable
            except ImportError:
                return None
            return StartupUnavailable("swipl-unavailable")
        return None

    def stop(self) -> None:
        self._tools = None
        self.engine = None
        self.store = None

    @staticmethod
    def _build_embedder(configuration: dict[str, object]):
        backend = str(configuration.get("embedding_backend", "disabled")).strip().lower()
        model = str(configuration.get("embedding_model", "nomic-embed-text")).strip() or "nomic-embed-text"
        timeout = float(configuration.get("embedding_timeout_seconds", 10.0))
        if backend == "disabled":
            return None
        if backend == "ollama":
            base_url = str(configuration.get("ollama_url", "http://127.0.0.1:11434")).strip()
            return OllamaEmbedder(base_url=base_url, model=model, timeout_seconds=timeout)
        if backend in {"openai", "openai-compatible"}:
            endpoint = str(configuration.get("embedding_endpoint", "")).strip()
            if not endpoint:
                raise SymbolicMemoryError("embedding_endpoint is required for openai-compatible embeddings")
            api_key = str(configuration.get("embedding_api_key", "")).strip()
            return OpenAICompatibleEmbedder(endpoint=endpoint, model=model, api_key=api_key, timeout_seconds=timeout)
        raise SymbolicMemoryError("unsupported embedding backend")

    def _require_store(self) -> SymbolicMemoryStore:
        if self.store is None:
            raise SymbolicMemoryError("symbolic memory plugin is not started")
        return self.store

    def _require_engine(self) -> PrologQueryEngine:
        if self.engine is None:
            raise SymbolicMemoryError("symbolic memory plugin is not started")
        return self.engine

    def remember(self, subject: str, predicate: str, object_json: str, scope: str = "global", source: str = "user", confidence: float = 1.0, importance: float = 0.5) -> str:
        result = self._require_store().remember(
            subject=subject,
            predicate=predicate,
            object_json=object_json,
            scope=scope,
            source=source,
            confidence=confidence,
            importance=importance,
        )
        return json.dumps(result, ensure_ascii=False, sort_keys=True)

    def query(self, query: str, scope: str = "global", limit: int = 8) -> str:
        return json.dumps(self._require_engine().query(query, scope=scope, limit=limit), ensure_ascii=False, sort_keys=True)

    def forget(self, memory_id: str, reason: str = "user-request") -> str:
        return json.dumps(self._require_store().forget(memory_id, reason=reason), ensure_ascii=False, sort_keys=True)

    def reindex(self) -> str:
        return json.dumps(self._require_store().rebuild_embeddings(self.kb_roots), ensure_ascii=False, sort_keys=True)

    def status(self) -> str:
        store_status = self._require_store().status()
        store_status["query_rules"] = str(self._require_engine().rules_path)
        store_status["prolog_ready"] = self._require_engine().ready()
        store_status["kb_roots"] = list(self.kb_roots)
        return json.dumps(store_status, ensure_ascii=False, sort_keys=True)

    def tools(self):
        if self._tools is None:
            from langchain_core.tools import StructuredTool

            self._tools = (
                StructuredTool.from_function(func=self.remember, name="memory.remember", description="Store or update one durable memory as canonical Prolog facts. object_json must be valid JSON. Embeddings are derived only after the symbolic write."),
                StructuredTool.from_function(func=self.query, name="memory.query", description="Query symbolic memory and indexed Prolog KB clauses. Prolog query rules control scope, admission, hybrid scoring, and ranking."),
                StructuredTool.from_function(func=self.forget, name="memory.forget", description="Tombstone one memory by id. Canonical history remains explicit; active queries exclude tombstoned versions."),
                StructuredTool.from_function(func=self.reindex, name="memory.reindex", description="Rebuild all derived embeddings from canonical memory facts and configured Prolog KB roots."),
                StructuredTool.from_function(func=self.status, name="memory.status", description="Return symbolic-memory paths, embedding backend, Prolog readiness, and KB roots."),
            )
        return self._tools


def create_plugin():
    from zara.plugins import PluginMetadata, ServicePlugin

    metadata = PluginMetadata(
        name=PLUGIN_NAME,
        version=PLUGIN_VERSION,
        api_version="1",
        description=PLUGIN_DESCRIPTION,
    )

    class ZaraSymbolicMemoryService(ZaraSymbolicMemoryPlugin, ServicePlugin):
        pass

    ZaraSymbolicMemoryService.metadata = metadata
    return ZaraSymbolicMemoryService()
