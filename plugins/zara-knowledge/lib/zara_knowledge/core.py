"""Provider-neutral sourced evidence model and aggregation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Protocol


@dataclass(frozen=True)
class SourcedResult:
    provider: str
    url: str
    title: str
    excerpt: str
    timestamp: str
    local: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class KnowledgeProvider(Protocol):
    name: str
    local: bool

    def search(self, query: str, *, count: int = 5, **parameters: Any) -> list[SourcedResult]: ...


class KnowledgeEngine:
    def __init__(self, providers: Iterable[KnowledgeProvider]) -> None:
        self.providers = tuple(providers)

    def search(self, query: str, *, count: int = 5, **parameters: Any) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip() or len(query) > 2048:
            raise ValueError("query must contain 1 to 2048 characters")
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 20:
            raise ValueError("count must be between 1 and 20")
        results: list[SourcedResult] = []
        errors: list[dict[str, str]] = []
        for provider in self.providers:
            try:
                contributed = provider.search(query.strip(), count=count, **parameters)
                results.extend(contributed)
            except Exception as error:
                errors.append(
                    {
                        "provider": str(getattr(provider, "name", type(provider).__name__)),
                        "kind": str(getattr(error, "kind", "unavailable")),
                        "message": str(error),
                    }
                )
        return {
            "query": query.strip(),
            "results": [result.as_dict() for result in results[:count]],
            "errors": errors,
        }
