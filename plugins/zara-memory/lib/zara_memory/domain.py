from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


class MemoryError(RuntimeError):
    pass


SCOPES = frozenset({"session", "user", "project", "machine", "global"})
_PREDICATE = re.compile(r"^([a-z][a-z0-9_]*)\(")


@dataclass(frozen=True)
class MemorySchema:
    name: str
    allowed_scopes: frozenset[str]
    allowed_fact_predicates: frozenset[str]

    def __post_init__(self) -> None:
        if not self.name or len(self.name) > 128:
            raise ValueError("memory schema name must contain 1 to 128 characters")
        if not self.allowed_scopes or not self.allowed_scopes <= SCOPES:
            raise ValueError("memory schema scopes must be supported Zara memory scopes")
        if not self.allowed_fact_predicates:
            raise ValueError("memory schema must allow at least one fact predicate")


class MemoryService:
    def __init__(self, backend: Any) -> None:
        self.backend = backend
        self._schemas: dict[str, MemorySchema] = {}

    @property
    def supported_scopes(self) -> frozenset[str]:
        return SCOPES

    def register_schema(self, schema: MemorySchema) -> None:
        if schema.name in self._schemas:
            raise MemoryError(f"memory schema already registered: {schema.name}")
        self._schemas[schema.name] = schema

    def remember(
        self,
        *,
        scope: str,
        owner: str,
        text: str,
        facts: Iterable[str],
        provenance: dict[str, Any],
        memory_type: str,
    ) -> dict[str, Any]:
        schema = self._schema(memory_type)
        self._validate_scope_owner(scope, owner)
        if scope not in schema.allowed_scopes:
            raise MemoryError(f"memory type {memory_type!r} is not allowed in scope {scope!r}")
        if not isinstance(text, str):
            raise MemoryError("memory text must be a string")
        if not isinstance(provenance, dict) or not provenance:
            raise MemoryError("memory provenance is required")
        normalized_facts = tuple(self._validate_fact(schema, fact) for fact in facts)
        result = self.backend.remember(
            scope=scope,
            owner=owner,
            text=text,
            facts=normalized_facts,
            provenance=dict(provenance),
            memory_type=memory_type,
        )
        return self._validate_memory(result, scope=scope, owner=owner, memory_type=memory_type)

    def recall(
        self,
        *,
        scope: str,
        owner: str,
        query: str | None = None,
        memory_type: str | None = None,
    ) -> list[dict[str, Any]]:
        self._validate_scope_owner(scope, owner)
        if memory_type is not None:
            schema = self._schema(memory_type)
            if scope not in schema.allowed_scopes:
                raise MemoryError(f"memory type {memory_type!r} is not readable in scope {scope!r}")
        callback = getattr(self.backend, "recall", None)
        if callback is None:
            raise MemoryError("memory backend does not support recall/search")
        items = callback(scope=scope, owner=owner, query=query, memory_type=memory_type)
        if not isinstance(items, list):
            raise MemoryError("memory backend returned invalid recall data")
        return [
            self._validate_memory(item, scope=scope, owner=owner, memory_type=memory_type)
            for item in items
        ]

    def forget(self, memory_id: str, *, scope: str, owner: str) -> dict[str, Any]:
        self._validate_scope_owner(scope, owner)
        if not isinstance(memory_id, str) or not memory_id:
            raise MemoryError("memory id is required")
        callback = getattr(self.backend, "forget", None)
        if callback is None:
            raise MemoryError("memory backend does not support forgetting")
        result = callback(memory_id=memory_id, scope=scope, owner=owner)
        if not isinstance(result, dict) or not isinstance(result.get("removed"), bool):
            raise MemoryError("memory backend returned invalid forget evidence")
        projections = result.get("projection_ids", [])
        if not isinstance(projections, list) or any(not isinstance(item, str) for item in projections):
            raise MemoryError("memory backend returned invalid projection cleanup evidence")
        return {"removed": result["removed"], "projection_ids": list(projections)}

    def observe_context(self, context: dict[str, Any]) -> None:
        if not isinstance(context, dict):
            raise MemoryError("transient context must be structured data")
        # Context is deliberately not persisted. Explicit remember() is the only write path.
        return None

    def _schema(self, memory_type: str) -> MemorySchema:
        schema = self._schemas.get(memory_type)
        if schema is None:
            raise MemoryError(f"memory schema is not registered: {memory_type}")
        return schema

    @staticmethod
    def _validate_scope_owner(scope: str, owner: str) -> None:
        if scope not in SCOPES:
            raise MemoryError(f"unsupported memory scope: {scope!r}")
        if not isinstance(owner, str) or not owner.strip():
            raise MemoryError("memory scope owner is required")

    @staticmethod
    def _validate_fact(schema: MemorySchema, fact: str) -> str:
        if not isinstance(fact, str):
            raise MemoryError("memory fact must be text")
        normalized = fact.strip().removesuffix(".").strip()
        match = _PREDICATE.match(normalized)
        if match is None:
            raise MemoryError("memory fact must be a predicate term")
        predicate = match.group(1)
        if predicate not in schema.allowed_fact_predicates:
            raise MemoryError(f"memory fact predicate is not allowed by schema: {predicate}")
        if ":-" in normalized or ";" in normalized or "\n" in normalized:
            raise MemoryError("memory fact contains executable control syntax")
        return normalized

    @staticmethod
    def _validate_memory(
        item: Any,
        *,
        scope: str,
        owner: str,
        memory_type: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(item, dict):
            raise MemoryError("memory backend returned an invalid memory")
        required_strings = ("id", "scope", "owner", "text", "type", "created_at")
        for field in required_strings:
            if not isinstance(item.get(field), str) or not item[field]:
                raise MemoryError(f"memory backend result is missing {field}")
        if item["scope"] != scope or item["owner"] != owner:
            raise MemoryError("memory backend violated requested scope isolation")
        if memory_type is not None and item["type"] != memory_type:
            raise MemoryError("memory backend violated requested memory type isolation")
        if not isinstance(item.get("provenance"), dict):
            raise MemoryError("memory backend result is missing provenance")
        facts = item.get("facts", [])
        if not isinstance(facts, list) or any(not isinstance(fact, str) for fact in facts):
            raise MemoryError("memory backend result has invalid symbolic facts")
        return dict(item)
