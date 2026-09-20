from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .embedding import Embedder, EmbeddingError


MAX_TEXT_BYTES = 16 * 1024
MAX_SCOPE_BYTES = 256
MAX_SOURCE_BYTES = 256
MAX_KB_FILES = 2048
MAX_KB_FILE_BYTES = 2 * 1024 * 1024
MAX_KB_CLAUSES = 100_000
MEMORY_FACT_RE = re.compile(
    r'^memory_fact\(("(?:[^"\\]|\\.)*"),(\d+),("(?:[^"\\]|\\.)*"),("(?:[^"\\]|\\.)*"),("(?:[^"\\]|\\.)*"),("(?:[^"\\]|\\.)*"),("(?:[^"\\]|\\.)*"),("(?:[^"\\]|\\.)*"),([0-9.eE+-]+),([0-9.eE+-]+),(\d+),("(?:[^"\\]|\\.)*"),("(?:[^"\\]|\\.)*")\)\.$'
)
TOMBSTONE_RE = re.compile(
    r'^memory_tombstone\(("(?:[^"\\]|\\.)*"),(\d+),("(?:[^"\\]|\\.)*"),(\d+),("(?:[^"\\]|\\.)*")\)\.$'
)


class SymbolicMemoryError(RuntimeError):
    pass


def _q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _finite_unit(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SymbolicMemoryError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise SymbolicMemoryError(f"{name} must be between 0 and 1")
    return number


def _bounded_text(value: object, name: str, limit: int = MAX_TEXT_BYTES) -> str:
    if not isinstance(value, str):
        raise SymbolicMemoryError(f"{name} must be a string")
    text = value.strip()
    if not text or len(text.encode("utf-8")) > limit:
        raise SymbolicMemoryError(f"{name} is empty or exceeds the byte limit")
    return text


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _normalized_render(subject: str, predicate: str, object_json: str) -> str:
    try:
        value = json.loads(object_json)
    except json.JSONDecodeError:
        value = object_json
    if isinstance(value, dict) and isinstance(value.get("text"), str):
        rendered = value["text"]
    elif isinstance(value, str):
        rendered = value
    else:
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return " ".join(f"{rendered}".split()) or " ".join(f"{subject} {predicate}".split())


def _stable_memory_id(scope: str, subject: str, predicate: str) -> str:
    digest = hashlib.sha256("\0".join((scope, subject, predicate)).encode("utf-8")).hexdigest()
    return digest[:24]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    version: int
    scope: str
    subject: str
    predicate: str
    object_json: str
    text: str
    source: str
    confidence: float
    importance: float
    created_epoch: int
    created_iso: str
    text_sha256: str


class SymbolicMemoryStore:
    def __init__(
        self,
        data_dir: str | os.PathLike[str],
        *,
        embedder: Embedder | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.memory_path = self.data_dir / "memory.pl"
        self.embeddings_path = self.data_dir / "embeddings.pl"
        self.embedder = embedder
        self.clock = clock
        self._ensure_files()

    def _ensure_files(self) -> None:
        if not self.memory_path.exists():
            self.memory_path.write_text("% Zara symbolic memory — canonical append-only facts.\n", encoding="utf-8")
        if not self.embeddings_path.exists():
            self.embeddings_path.write_text("% Derived embedding cache. Safe to delete and rebuild.\n", encoding="utf-8")

    def _append(self, path: Path, line: str) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _versions(self) -> dict[str, int]:
        versions: dict[str, int] = {}
        for line in self.memory_path.read_text(encoding="utf-8").splitlines():
            match = MEMORY_FACT_RE.match(line)
            if match:
                memory_id = json.loads(match.group(1))
                versions[memory_id] = max(versions.get(memory_id, 0), int(match.group(2)))
                continue
            match = TOMBSTONE_RE.match(line)
            if match:
                memory_id = json.loads(match.group(1))
                versions[memory_id] = max(versions.get(memory_id, 0), int(match.group(2)))
        return versions

    def _tombstone_versions(self) -> dict[str, int]:
        versions: dict[str, int] = {}
        for line in self.memory_path.read_text(encoding="utf-8").splitlines():
            match = TOMBSTONE_RE.match(line)
            if not match:
                continue
            memory_id = json.loads(match.group(1))
            versions[memory_id] = max(versions.get(memory_id, 0), int(match.group(2)))
        return versions

    def records(self) -> list[MemoryRecord]:
        records: list[MemoryRecord] = []
        for line in self.memory_path.read_text(encoding="utf-8").splitlines():
            match = MEMORY_FACT_RE.match(line)
            if not match:
                continue
            groups = match.groups()
            records.append(
                MemoryRecord(
                    memory_id=json.loads(groups[0]),
                    version=int(groups[1]),
                    scope=json.loads(groups[2]),
                    subject=json.loads(groups[3]),
                    predicate=json.loads(groups[4]),
                    object_json=json.loads(groups[5]),
                    text=json.loads(groups[6]),
                    source=json.loads(groups[7]),
                    confidence=float(groups[8]),
                    importance=float(groups[9]),
                    created_epoch=int(groups[10]),
                    created_iso=json.loads(groups[11]),
                    text_sha256=json.loads(groups[12]),
                )
            )
        return records

    def active_records(self) -> list[MemoryRecord]:
        latest: dict[str, MemoryRecord] = {}
        for record in self.records():
            previous = latest.get(record.memory_id)
            if previous is None or record.version > previous.version:
                latest[record.memory_id] = record
        tombstones = self._tombstone_versions()
        return sorted(
            (
                record
                for memory_id, record in latest.items()
                if tombstones.get(memory_id, 0) < record.version
            ),
            key=lambda record: (record.created_epoch, record.memory_id),
        )

    def remember(
        self,
        *,
        subject: str,
        predicate: str,
        object_json: str,
        scope: str = "global",
        source: str = "user",
        confidence: float = 1.0,
        importance: float = 0.5,
    ) -> dict[str, object]:
        subject = _bounded_text(subject, "memory subject")
        predicate = _bounded_text(predicate, "memory predicate")
        scope = _bounded_text(scope, "memory scope", MAX_SCOPE_BYTES)
        source = _bounded_text(source, "memory source", MAX_SOURCE_BYTES)
        confidence = _finite_unit(confidence, "memory confidence")
        importance = _finite_unit(importance, "memory importance")
        object_json = _bounded_text(object_json, "memory object")
        try:
            value = json.loads(object_json)
        except json.JSONDecodeError as error:
            raise SymbolicMemoryError("memory object must be valid JSON") from error
        object_json = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        text = _normalized_render(subject, predicate, object_json)
        memory_id = _stable_memory_id(scope, subject, predicate)
        version = self._versions().get(memory_id, 0) + 1
        created_epoch = int(self.clock())
        created_iso = _iso(created_epoch)
        text_sha256 = _sha(text)
        fact = (
            f"memory_fact({_q(memory_id)},{version},{_q(scope)},{_q(subject)},{_q(predicate)},"
            f"{_q(object_json)},{_q(text)},{_q(source)},{confidence:.12g},{importance:.12g},"
            f"{created_epoch},{_q(created_iso)},{_q(text_sha256)})."
        )
        self._append(self.memory_path, fact)
        embedding_status = "disabled"
        if self.embedder is not None:
            try:
                vector = self.embedder.embed([text])[0]
                self._append_embedding(memory_id, version, text_sha256, vector)
                embedding_status = "indexed"
            except EmbeddingError:
                self._append(
                    self.embeddings_path,
                    f"embedding_pending({_q(memory_id)},{version},{_q(text_sha256)},{_q('provider-error')}).",
                )
                embedding_status = "pending"
        return {
            "status": "ok",
            "memory_id": memory_id,
            "version": version,
            "embedding": embedding_status,
            "canonical": str(self.memory_path),
        }

    def forget(self, memory_id: str, *, reason: str = "user-request") -> dict[str, object]:
        memory_id = _bounded_text(memory_id, "memory id", 128)
        reason = _bounded_text(reason, "forget reason", 256)
        active = {record.memory_id: record for record in self.active_records()}
        record = active.get(memory_id)
        if record is None:
            return {"status": "not-found", "memory_id": memory_id}
        version = max(record.version, self._versions().get(memory_id, 0)) + 1
        epoch = int(self.clock())
        self._append(
            self.memory_path,
            f"memory_tombstone({_q(memory_id)},{version},{_q(reason)},{epoch},{_q(_iso(epoch))}).",
        )
        return {"status": "ok", "memory_id": memory_id, "version": version}

    def _append_embedding(self, memory_id: str, version: int, text_sha256: str, vector: Sequence[float]) -> None:
        if self.embedder is None:
            raise SymbolicMemoryError("embedding backend is not configured")
        rendered = ",".join(f"{float(value):.12g}" for value in vector)
        self._append(
            self.embeddings_path,
            f"memory_embedding({_q(memory_id)},{version},{_q(self.embedder.model)},{len(vector)},{_q(text_sha256)},[{rendered}]).",
        )

    def rebuild_embeddings(self, kb_roots: Iterable[str | os.PathLike[str]] = ()) -> dict[str, object]:
        if self.embedder is None:
            raise SymbolicMemoryError("embedding backend is not configured")
        memory_records = self.active_records()
        kb_clauses = list(self._load_kb_clauses(kb_roots))
        items: list[tuple[str, object]] = [("memory", record) for record in memory_records]
        items.extend(("kb", clause) for clause in kb_clauses)
        lines = ["% Derived embedding cache. Safe to delete and rebuild."]
        for offset in range(0, len(items), 32):
            batch = items[offset : offset + 32]
            texts = [item.text if kind == "memory" else item[3] for kind, item in batch]
            vectors = self.embedder.embed(texts)
            for (kind, item), vector in zip(batch, vectors):
                rendered = ",".join(f"{float(value):.12g}" for value in vector)
                if kind == "memory":
                    record = item
                    lines.append(
                        f"memory_embedding({_q(record.memory_id)},{record.version},{_q(self.embedder.model)},{len(vector)},{_q(record.text_sha256)},[{rendered}])."
                    )
                else:
                    clause_id, source, clause_sha, text = item
                    lines.append(
                        f"kb_clause({_q(clause_id)},{_q(source)},{_q(clause_sha)},{_q(text)})."
                    )
                    lines.append(
                        f"kb_embedding({_q(clause_id)},{_q(self.embedder.model)},{len(vector)},{_q(clause_sha)},[{rendered}])."
                    )
        self._atomic_write(self.embeddings_path, "\n".join(lines) + "\n")
        return {
            "status": "ok",
            "active_memories": len(memory_records),
            "kb_clauses": len(kb_clauses),
            "model": self.embedder.model,
        }

    def status(self) -> dict[str, object]:
        return {
            "status": "ok",
            "canonical_memory": str(self.memory_path),
            "derived_embeddings": str(self.embeddings_path),
            "memory_versions": len(self.records()),
            "active_memories": len(self.active_records()),
            "embedding_backend": None if self.embedder is None else self.embedder.model,
        }

    def _atomic_write(self, path: Path, content: str) -> None:
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _load_kb_clauses(self, roots: Iterable[str | os.PathLike[str]]):
        count = 0
        files_seen = 0
        for root in roots:
            root_path = Path(root).expanduser().resolve()
            if not root_path.exists():
                continue
            candidates = [root_path] if root_path.is_file() else sorted(root_path.rglob("*.pl"))
            for path in candidates:
                if path.suffix != ".pl" or not path.is_file():
                    continue
                files_seen += 1
                if files_seen > MAX_KB_FILES:
                    raise SymbolicMemoryError("Prolog KB file limit exceeded")
                if path.stat().st_size > MAX_KB_FILE_BYTES:
                    raise SymbolicMemoryError("Prolog KB file exceeds byte limit")
                text = path.read_text(encoding="utf-8")
                source = str(path)
                for clause in _split_prolog_clauses(text):
                    normalized = " ".join(clause.split())
                    if not normalized or normalized.startswith(":-") and "module(" in normalized:
                        continue
                    count += 1
                    if count > MAX_KB_CLAUSES:
                        raise SymbolicMemoryError("Prolog KB clause limit exceeded")
                    clause_sha = _sha(normalized)
                    clause_id = hashlib.sha256(f"{source}\0{clause_sha}".encode("utf-8")).hexdigest()[:24]
                    yield clause_id, source, clause_sha, normalized


def _split_prolog_clauses(text: str) -> list[str]:
    clauses: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    depth = 0
    comment = False
    index = 0
    while index < len(text):
        char = text[index]
        if comment:
            if char == "\n":
                comment = False
                current.append(char)
            index += 1
            continue
        if quote is None and char == "%":
            comment = True
            index += 1
            continue
        if quote is not None:
            current.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in ("'", '"'):
            quote = char
            current.append(char)
            index += 1
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        current.append(char)
        if char == "." and depth == 0:
            clause = "".join(current).strip()
            if clause:
                clauses.append(clause)
            current = []
        index += 1
    remainder = "".join(current).strip()
    if remainder:
        clauses.append(remainder)
    return clauses
