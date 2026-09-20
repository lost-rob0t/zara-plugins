from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Iterable

from .embedding import OllamaEmbedder, OpenAICompatibleEmbedder
from .prolog import PrologQueryEngine
from .store import MemoryRecord, SymbolicMemoryError, SymbolicMemoryStore


PLUGIN_NAME = "zara-symbolic-memory"
PLUGIN_VERSION = "0.1.0"
PLUGIN_DESCRIPTION = "Prolog-authoritative symbolic memory with Prolog-resident embedding indexes and query rules"
MAX_SESSION_MESSAGES = 256
MAX_SESSION_TEXT_BYTES = 16 * 1024
TRANSIENT_PRINCIPAL_KINDS = frozenset({"guest", "ephemeral"})


def _clean_text(value: object, name: str, limit: int = MAX_SESSION_TEXT_BYTES) -> str:
    if not isinstance(value, str):
        raise SymbolicMemoryError(f"{name} must be a string")
    text = value.strip()
    if not text or len(text.encode("utf-8")) > limit:
        raise SymbolicMemoryError(f"{name} is empty or exceeds the byte limit")
    return text


def _normalize_tags(tags: Iterable[str] | None) -> list[str]:
    if not tags:
        return []
    values = [str(tag).strip() for tag in tags if str(tag).strip()]
    return list(dict.fromkeys(values))[:32]


class ZaraSymbolicMemoryPlugin:
    def __init__(self) -> None:
        self.store: SymbolicMemoryStore | None = None
        self.engine: PrologQueryEngine | None = None
        self.kb_roots: tuple[str, ...] = ()
        self.current_session_id: str | None = None
        self._sessions: dict[str, list[tuple[str, str]]] = {}
        self._principal_id: str | None = None
        self._principal_kind = ""
        self._transient = False
        self._tools = None

    def start(self, runtime):
        configuration = dict(runtime.configuration)
        data_dir = configuration.get("data_dir") or os.getenv("ZARA_SYMBOLIC_MEMORY_DIR")
        if not data_dir:
            data_root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
            data_dir = str(data_root / "zara" / "symbolic-memory")
        embedder = self._build_embedder(configuration)
        self.kb_roots = tuple(
            str(value)
            for value in configuration.get("kb_roots", ())
            if str(value).strip()
        )
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
        register_symbol = getattr(runtime, "register_symbol", None)
        if not callable(register_symbol):
            try:
                from zara.plugins import StartupUnavailable
            except ImportError:
                return None
            return StartupUnavailable("symbol-registry-unavailable")
        register_symbol(
            "memory.provider",
            "memory-provider",
            self,
            docs="Prolog-authoritative Zara memory provider with derived memory and Prolog-KB embeddings.",
            source=PLUGIN_NAME,
        )
        return None

    def stop(self) -> None:
        self._tools = None
        self.engine = None
        self.store = None
        self.current_session_id = None
        self._sessions.clear()
        self._principal_id = None
        self._principal_kind = ""
        self._transient = False

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
            return OpenAICompatibleEmbedder(
                endpoint=endpoint,
                model=model,
                api_key=api_key,
                timeout_seconds=timeout,
            )
        raise SymbolicMemoryError("unsupported embedding backend")

    def bind_principal(self, principal) -> None:
        principal_id = getattr(principal, "principal_id", None)
        principal_kind = getattr(principal, "kind", "local-owner")
        if not isinstance(principal_id, str) or not principal_id.strip() or principal_id != principal_id.strip():
            raise SymbolicMemoryError("memory provider requires a valid principal id")
        if not isinstance(principal_kind, str) or not principal_kind.strip():
            raise SymbolicMemoryError("memory provider requires a valid principal kind")
        self._principal_id = principal_id
        self._principal_kind = principal_kind
        self._transient = principal_kind in TRANSIENT_PRINCIPAL_KINDS

    def _scope(self) -> str:
        if self._principal_id is None:
            raise SymbolicMemoryError("memory provider is not bound to a principal")
        return f"principal:{self._principal_id}"

    def _require_store(self) -> SymbolicMemoryStore:
        if self.store is None:
            raise SymbolicMemoryError("symbolic memory plugin is not started")
        return self.store

    def _require_engine(self) -> PrologQueryEngine:
        if self.engine is None:
            raise SymbolicMemoryError("symbolic memory plugin is not started")
        return self.engine

    def start_session(self, session_id: str | None = None) -> str:
        session = session_id or str(uuid.uuid4())
        session = _clean_text(session, "session id", 256)
        self._sessions[session] = []
        self.current_session_id = session
        return session

    def add_message(self, session_id: str, role: str, content: str) -> None:
        session = _clean_text(session_id, "session id", 256)
        role = _clean_text(role, "message role", 64)
        content = _clean_text(content, "message content")
        messages = self._sessions.setdefault(session, [])
        if len(messages) >= MAX_SESSION_MESSAGES:
            raise SymbolicMemoryError("memory session message limit reached")
        messages.append((role, content))

    def summarise_session(
        self,
        session_id: str,
        summary_text: str | None = None,
        source: str = "wake",
    ) -> str | None:
        session = _clean_text(session_id, "session id", 256)
        messages = self._sessions.get(session, [])
        if summary_text is None:
            if not messages:
                return None
            text = "\n".join(f"{role}: {content}" for role, content in messages)
            kind = "transcript"
        else:
            text = _clean_text(summary_text, "session summary")
            kind = "summary"
        text = text[:MAX_SESSION_TEXT_BYTES].rstrip()
        if not text or self._transient:
            return text or None
        payload = {
            "kind": kind,
            "session_id": session,
            "tags": [kind],
            "text": text,
        }
        self._require_store().remember(
            subject=f"session:{session}",
            predicate=kind,
            object_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            scope=self._scope(),
            source=source,
            confidence=1.0,
            importance=0.4,
        )
        return text

    def remember_fact(
        self,
        text: str,
        tags: list[str] | None = None,
        session_id: str | None = None,
        source: str = "agent",
    ) -> str | None:
        text = _clean_text(text, "memory text")
        if self._transient:
            return None
        tag_list = _normalize_tags(tags)
        digest = hashlib.sha256(text.casefold().encode("utf-8")).hexdigest()[:20]
        payload = {
            "kind": "fact",
            "session_id": session_id or self.current_session_id or "",
            "tags": tag_list,
            "text": text,
        }
        result = self._require_store().remember(
            subject=f"fact:{digest}",
            predicate="fact",
            object_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            scope=self._scope(),
            source=source,
            confidence=1.0,
            importance=0.6,
        )
        return str(result["memory_id"])

    @staticmethod
    def _payload(record: MemoryRecord) -> dict[str, object]:
        try:
            value = json.loads(record.object_json)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    def _record_entry(self, record: MemoryRecord) -> dict[str, object]:
        payload = self._payload(record)
        return {
            "id": record.memory_id,
            "text": str(payload.get("text") or record.text),
            "metadata": {
                "kind": str(payload.get("kind") or record.predicate),
                "tags": list(payload.get("tags") or []),
                "session_id": str(payload.get("session_id") or ""),
                "source": record.source,
                "created_at": record.created_iso,
                "scope": record.scope,
                "record_type": "memory",
            },
        }

    def retrieve(
        self,
        query: str,
        k: int | None = None,
        include_kinds: Iterable[str] | None = None,
        tags: list[str] | None = None,
    ) -> list[dict[str, object]]:
        limit = 5 if k is None else int(k)
        result = self._require_engine().query(query, scope=self._scope(), limit=max(1, min(limit, 32)))
        kinds = set(include_kinds) if include_kinds else None
        required_tags = set(_normalize_tags(tags))
        entries: list[dict[str, object]] = []
        for item in result.get("results", []):
            if not isinstance(item, dict):
                continue
            if item.get("type") == "kb":
                if kinds is not None and "prolog-kb" not in kinds:
                    continue
                entries.append(
                    {
                        "id": item.get("clause_id"),
                        "text": item.get("text", ""),
                        "metadata": {
                            "kind": "prolog-kb",
                            "tags": [],
                            "session_id": "",
                            "source": item.get("source", ""),
                            "record_type": "kb",
                        },
                        "score": item.get("score"),
                    }
                )
                continue
            if item.get("type") != "memory":
                continue
            try:
                payload = json.loads(item.get("object_json", "{}"))
            except (TypeError, json.JSONDecodeError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            kind = str(payload.get("kind") or item.get("predicate") or "fact")
            stored_tags = set(str(tag) for tag in payload.get("tags", []) if str(tag))
            if kinds is not None and kind not in kinds:
                continue
            if required_tags and not required_tags.issubset(stored_tags):
                continue
            entries.append(
                {
                    "id": item.get("memory_id"),
                    "text": str(payload.get("text") or item.get("text", "")),
                    "metadata": {
                        "kind": kind,
                        "tags": sorted(stored_tags),
                        "session_id": str(payload.get("session_id") or ""),
                        "source": item.get("source", ""),
                        "created_at": item.get("created_at", ""),
                        "scope": item.get("scope", ""),
                        "record_type": "memory",
                    },
                    "score": item.get("score"),
                }
            )
        return entries[:limit]

    def list_memories(
        self,
        limit: int = 50,
        include_kinds: Iterable[str] | None = None,
        tags: list[str] | None = None,
        session_id: str | None = None,
    ) -> list[dict[str, object]]:
        kinds = set(include_kinds) if include_kinds else None
        required_tags = set(_normalize_tags(tags))
        records = [
            record
            for record in self._require_store().active_records()
            if record.scope == self._scope()
        ]
        entries: list[dict[str, object]] = []
        for record in sorted(records, key=lambda item: item.created_epoch, reverse=True):
            entry = self._record_entry(record)
            metadata = entry["metadata"]
            if kinds is not None and metadata["kind"] not in kinds:
                continue
            if required_tags and not required_tags.issubset(set(metadata["tags"])):
                continue
            if session_id is not None and metadata["session_id"] != session_id:
                continue
            entries.append(entry)
        return entries[: max(0, int(limit))]

    def forget(
        self,
        *,
        memory_id: str | None = None,
        query: str | None = None,
        session_id: str | None = None,
        all_memories: bool = False,
        include_kinds: Iterable[str] | None = None,
        tags: list[str] | None = None,
    ) -> int:
        selectors = sum(
            bool(value)
            for value in (memory_id, (query or "").strip(), session_id, all_memories)
        )
        if selectors != 1:
            raise ValueError("Choose exactly one memory deletion scope")
        candidates = self.list_memories(
            limit=100_000,
            include_kinds=include_kinds,
            tags=tags,
            session_id=session_id if session_id else None,
        )
        if memory_id:
            candidates = [entry for entry in candidates if entry["id"] == memory_id]
        elif query:
            ranked = self.retrieve(query, k=32, include_kinds=include_kinds, tags=tags)
            selected = {
                entry["id"]
                for entry in ranked
                if entry.get("metadata", {}).get("record_type") == "memory"
            }
            candidates = [entry for entry in candidates if entry["id"] in selected]
        elif not all_memories and session_id is None:
            candidates = []
        deleted = 0
        for entry in candidates:
            result = self._require_store().forget(str(entry["id"]), reason="user-request")
            if result.get("status") == "ok":
                deleted += 1
        if session_id:
            self._sessions.pop(session_id, None)
            if self.current_session_id == session_id:
                self.current_session_id = None
        if all_memories:
            self._sessions.clear()
            self.current_session_id = None
        return deleted

    def clear_principal_state(self) -> None:
        self.forget(all_memories=True)

    def get_health(self) -> dict[str, object]:
        return {
            "status": "symbolic" if self._require_engine().ready() else "unavailable",
            "error": None if self._require_engine().ready() else "SWI-Prolog unavailable",
        }

    def remember(
        self,
        subject: str,
        predicate: str,
        object_json: str,
        confidence: float = 1.0,
        importance: float = 0.5,
    ) -> str:
        result = self._require_store().remember(
            subject=subject,
            predicate=predicate,
            object_json=object_json,
            scope=self._scope(),
            source="agent",
            confidence=confidence,
            importance=importance,
        )
        return json.dumps(result, ensure_ascii=False, sort_keys=True)

    def query(self, query: str, limit: int = 8) -> str:
        return json.dumps(
            self._require_engine().query(query, scope=self._scope(), limit=limit),
            ensure_ascii=False,
            sort_keys=True,
        )

    def forget_one(self, memory_id: str, reason: str = "user-request") -> str:
        record = next(
            (
                item
                for item in self._require_store().active_records()
                if item.memory_id == memory_id and item.scope == self._scope()
            ),
            None,
        )
        if record is None:
            return json.dumps({"status": "not-found", "memory_id": memory_id}, sort_keys=True)
        return json.dumps(
            self._require_store().forget(memory_id, reason=reason),
            ensure_ascii=False,
            sort_keys=True,
        )

    def reindex(self) -> str:
        return json.dumps(
            self._require_store().rebuild_embeddings(self.kb_roots),
            ensure_ascii=False,
            sort_keys=True,
        )

    def status(self) -> str:
        store_status = self._require_store().status()
        store_status["query_rules"] = str(self._require_engine().rules_path)
        store_status["prolog_ready"] = self._require_engine().ready()
        store_status["kb_roots"] = list(self.kb_roots)
        store_status["principal_bound"] = self._principal_id is not None
        return json.dumps(store_status, ensure_ascii=False, sort_keys=True)

    def tools(self):
        if self._tools is None:
            from langchain_core.tools import StructuredTool

            self._tools = (
                StructuredTool.from_function(
                    func=self.remember,
                    name="memory.remember",
                    description="Assert or version one symbolic memory. The canonical write is a Prolog fact; its embedding is derived afterward.",
                ),
                StructuredTool.from_function(
                    func=self.query,
                    name="memory.query",
                    description="Run Prolog-governed hybrid retrieval across principal memory and indexed Prolog KB clauses.",
                ),
                StructuredTool.from_function(
                    func=self.forget_one,
                    name="memory.forget",
                    description="Tombstone one principal-owned memory by id without deleting canonical history.",
                ),
                StructuredTool.from_function(
                    func=self.reindex,
                    name="memory.reindex",
                    description="Rebuild derived memory and Prolog-KB embeddings from canonical Prolog sources.",
                ),
                StructuredTool.from_function(
                    func=self.status,
                    name="memory.status",
                    description="Return symbolic-memory paths, embedding backend, query-rule path, and Prolog readiness.",
                ),
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
