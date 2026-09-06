from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Sequence


class MemoryError(RuntimeError):
    pass


SCOPES = frozenset({"session", "user", "project", "machine", "global"})
_PREDICATE = re.compile(r"^([a-z][a-z0-9_]*)\(.*\)$")


@dataclass(frozen=True)
class MemorySchema:
    name: str
    allowed_scopes: frozenset[str]
    allowed_fact_predicates: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 128:
            raise ValueError("memory schema name must contain 1 to 128 characters")
        if (
            not isinstance(self.allowed_scopes, frozenset)
            or not self.allowed_scopes
            or any(not isinstance(scope, str) or not scope.strip() for scope in self.allowed_scopes)
            or not self.allowed_scopes <= SCOPES
        ):
            raise ValueError("memory schema scopes must be supported Zara memory scopes")
        if (
            not isinstance(self.allowed_fact_predicates, frozenset)
            or not self.allowed_fact_predicates
            or any(
                not isinstance(predicate, str) or not predicate.strip()
                for predicate in self.allowed_fact_predicates
            )
        ):
            raise ValueError("memory schema must allow non-empty fact predicates")


class MemoryService:
    MAX_FACTS = 64
    MAX_RECALL_RESULTS = 64

    def __init__(self, backend: Any) -> None:
        self.backend = backend
        self._schemas: dict[str, MemorySchema] = {}

    @property
    def supported_scopes(self) -> frozenset[str]:
        return SCOPES

    def register_schema(self, schema: MemorySchema) -> None:
        if not isinstance(schema, MemorySchema):
            raise MemoryError("memory schema registration requires MemorySchema")
        if schema.name in self._schemas:
            raise MemoryError(f"memory schema already registered: {schema.name}")
        self._schemas[schema.name] = schema

    def remember(
        self,
        *,
        scope: str,
        owner: str,
        text: str,
        facts: Sequence[str],
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
        if isinstance(facts, (str, bytes)) or not isinstance(facts, Sequence):
            raise MemoryError("memory facts must be a sequence of fact strings")
        if len(facts) > self.MAX_FACTS:
            raise MemoryError(f"memory facts exceed {self.MAX_FACTS} item limit")
        normalized_facts = tuple(self._validate_fact(schema, fact) for fact in facts)
        expected_provenance = copy.deepcopy(provenance)
        result = self.backend.remember(
            scope=scope,
            owner=owner,
            text=text,
            facts=normalized_facts,
            provenance=copy.deepcopy(expected_provenance),
            memory_type=memory_type,
        )
        validated = self._validate_memory(result, scope=scope, owner=owner, memory_type=memory_type)
        if (
            validated["text"] != text
            or tuple(validated["facts"]) != normalized_facts
            or validated["provenance"] != expected_provenance
        ):
            raise MemoryError("memory backend returned mismatched write evidence")
        return validated

    def recall(
        self,
        *,
        scope: str,
        owner: str,
        query: str | None = None,
        memory_type: str | None = None,
    ) -> list[dict[str, Any]]:
        self._validate_scope_owner(scope, owner)
        if query is not None and not isinstance(query, str):
            raise MemoryError("memory query must be text")
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
        if len(items) > self.MAX_RECALL_RESULTS:
            raise MemoryError(
                f"memory backend returned more than {self.MAX_RECALL_RESULTS} recall results"
            )
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
        return None

    def _schema(self, memory_type: str) -> MemorySchema:
        if not isinstance(memory_type, str) or not memory_type.strip():
            raise MemoryError("memory type must be non-empty text")
        schema = self._schemas.get(memory_type)
        if schema is None:
            raise MemoryError(f"memory schema is not registered: {memory_type}")
        return schema

    @staticmethod
    def _validate_scope_owner(scope: str, owner: str) -> None:
        if not isinstance(scope, str) or scope not in SCOPES:
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

    def _validate_memory(
        self,
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
        schema = self._schema(item["type"])
        if scope not in schema.allowed_scopes:
            raise MemoryError("memory backend violated registered schema scope isolation")
        if not isinstance(item.get("provenance"), dict) or not item["provenance"]:
            raise MemoryError("memory backend result is missing provenance")
        facts = item.get("facts", [])
        if not isinstance(facts, list):
            raise MemoryError("memory backend result has invalid symbolic facts")
        if len(facts) > self.MAX_FACTS:
            raise MemoryError(f"memory backend result exceeds {self.MAX_FACTS} symbolic facts")
        validated_facts = [self._validate_fact(schema, fact) for fact in facts]
        result = dict(item)
        result["facts"] = validated_facts
        return result
