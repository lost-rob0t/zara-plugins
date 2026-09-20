"""Local imported-wiki storage and provider adapter."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .core import SourcedResult


class WikiStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS wiki_pages (
                    gate TEXT NOT NULL,
                    page_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    revision_id INTEGER,
                    revision_timestamp TEXT NOT NULL,
                    content TEXT NOT NULL,
                    categories_json TEXT NOT NULL,
                    links_json TEXT NOT NULL,
                    wikidata_id TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    PRIMARY KEY (gate, page_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS wiki_pages_title_idx ON wiki_pages(gate, title)"
            )

    def upsert(self, page: dict[str, Any]) -> dict[str, Any]:
        gate = _required_text(page, "gate")
        page_id = _required_int(page, "page_id")
        title = _required_text(page, "title")
        canonical_url = _required_text(page, "canonical_url")
        revision_id = _optional_int(page.get("revision_id"))
        revision_timestamp = str(page.get("revision_timestamp") or "")
        content = str(page.get("content") or "")
        categories = _string_list(page.get("categories", []), "categories")
        links = _string_list(page.get("links", []), "links")
        wikidata_id = str(page.get("wikidata_id") or "")
        imported_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO wiki_pages (
                    gate, page_id, title, canonical_url, revision_id,
                    revision_timestamp, content, categories_json, links_json,
                    wikidata_id, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(gate, page_id) DO UPDATE SET
                    title=excluded.title,
                    canonical_url=excluded.canonical_url,
                    revision_id=excluded.revision_id,
                    revision_timestamp=excluded.revision_timestamp,
                    content=excluded.content,
                    categories_json=excluded.categories_json,
                    links_json=excluded.links_json,
                    wikidata_id=excluded.wikidata_id,
                    imported_at=excluded.imported_at
                """,
                (
                    gate,
                    page_id,
                    title,
                    canonical_url,
                    revision_id,
                    revision_timestamp,
                    content,
                    json.dumps(categories, ensure_ascii=False),
                    json.dumps(links, ensure_ascii=False),
                    wikidata_id,
                    imported_at,
                ),
            )
        return self.get(gate, page_id)

    def get(self, gate: str, page_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM wiki_pages WHERE gate = ? AND page_id = ?",
                (gate, page_id),
            ).fetchone()
        return None if row is None else _row_to_page(row)

    def search(
        self,
        query: str,
        *,
        count: int = 5,
        gates: Iterable[str] | None = None,
    ) -> list[SourcedResult]:
        if not isinstance(query, str) or not query.strip() or len(query) > 2048:
            raise ValueError("query must contain 1 to 2048 characters")
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 20:
            raise ValueError("count must be between 1 and 20")

        normalized = query.strip().lower()
        like = f"%{normalized}%"
        selected = tuple(dict.fromkeys(str(item).strip() for item in (gates or ()) if str(item).strip()))
        sql = """
            SELECT *
            FROM wiki_pages
            WHERE (lower(title) LIKE ? OR lower(content) LIKE ?)
        """
        parameters: list[Any] = [like, like]
        if selected:
            placeholders = ",".join("?" for _ in selected)
            sql += f" AND gate IN ({placeholders})"
            parameters.extend(selected)
        sql += """
            ORDER BY
                CASE
                    WHEN lower(title) = ? THEN 0
                    WHEN lower(title) LIKE ? THEN 1
                    ELSE 2
                END,
                imported_at DESC
            LIMIT ?
        """
        parameters.extend([normalized, like, count])

        with self._connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()

        results: list[SourcedResult] = []
        for row in rows:
            excerpt = _excerpt(str(row["content"]), normalized)
            results.append(
                SourcedResult(
                    provider="wiki-import",
                    url=str(row["canonical_url"]),
                    title=str(row["title"]),
                    excerpt=excerpt,
                    timestamp=str(row["revision_timestamp"] or row["imported_at"]),
                    local=True,
                    gate=str(row["gate"]),
                )
            )
        return results

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM wiki_pages").fetchone()
        return int(row["count"])


class LocalWikiProvider:
    name = "wiki-import"
    local = True

    def __init__(self, store: WikiStore) -> None:
        self.store = store

    def search(self, query: str, *, count: int = 5, **parameters: Any) -> list[SourcedResult]:
        gates = parameters.get("gates")
        if isinstance(gates, str):
            gates = [item.strip() for item in gates.split(",") if item.strip()]
        return self.store.search(query, count=count, gates=gates)


def _required_text(page: dict[str, Any], key: str) -> str:
    value = page.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _required_int(page: dict[str, Any], key: str) -> int:
    value = page.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("revision_id must be an integer or null")
    return value


def _string_list(value: Any, key: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be a list of strings")
    return [item for item in value if item]


def _row_to_page(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "gate": str(row["gate"]),
        "page_id": int(row["page_id"]),
        "title": str(row["title"]),
        "canonical_url": str(row["canonical_url"]),
        "revision_id": None if row["revision_id"] is None else int(row["revision_id"]),
        "revision_timestamp": str(row["revision_timestamp"]),
        "content": str(row["content"]),
        "categories": json.loads(str(row["categories_json"])),
        "links": json.loads(str(row["links_json"])),
        "wikidata_id": str(row["wikidata_id"]),
        "imported_at": str(row["imported_at"]),
    }


def _excerpt(content: str, query: str, limit: int = 480) -> str:
    if len(content) <= limit:
        return content
    index = content.lower().find(query)
    if index < 0:
        return content[:limit].rstrip() + "…"
    start = max(0, index - limit // 3)
    end = min(len(content), start + limit)
    excerpt = content[start:end].strip()
    if start:
        excerpt = "…" + excerpt
    if end < len(content):
        excerpt += "…"
    return excerpt
