from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .embedding import Embedder
from .store import SymbolicMemoryError, SymbolicMemoryStore


MAX_QUERY_BYTES = 4096
MAX_QUERY_LIMIT = 32
TOKEN_RE = re.compile(r"[\w'-]+", re.UNICODE)
STOP_WORDS = frozenset({"a", "an", "and", "are", "for", "from", "i", "in", "is", "it", "me", "my", "of", "on", "that", "the", "to", "was", "what", "with", "you"})


class PrologQueryEngine:
    def __init__(self, store: SymbolicMemoryStore, rules_path: str | os.PathLike[str], *, embedder: Embedder | None = None) -> None:
        self.store = store
        self.rules_path = Path(rules_path)
        self.embedder = embedder

    def ready(self) -> bool:
        return shutil.which("swipl") is not None and self.rules_path.is_file()

    def query(self, text: str, *, scope: str = "global", limit: int = 8) -> dict[str, object]:
        if not self.ready():
            raise SymbolicMemoryError("SWI-Prolog query runtime is unavailable")
        if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > MAX_QUERY_BYTES:
            raise SymbolicMemoryError("memory query is empty or exceeds the byte limit")
        if not isinstance(scope, str) or not scope.strip() or len(scope.encode("utf-8")) > 256:
            raise SymbolicMemoryError("memory query scope is invalid")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_QUERY_LIMIT:
            raise SymbolicMemoryError("memory query limit is out of range")
        normalized = " ".join(text.casefold().split())
        tokens = [token for token in TOKEN_RE.findall(normalized) if len(token) > 1 and token not in STOP_WORDS]
        tokens = tokens or TOKEN_RE.findall(normalized)
        vector: list[float] = []
        if self.embedder is not None:
            vector = self.embedder.embed([normalized])[0]
        payload = {
            "query": normalized,
            "tokens": tokens[:32],
            "scope": scope.strip(),
            "limit": limit,
            "now": int(time.time()),
            "vector": vector,
            "model": "" if self.embedder is None else self.embedder.model,
        }
        query_file = self._query_file(payload)
        try:
            command = [
                "swipl",
                "-q",
                "-s",
                str(self.rules_path),
                "-s",
                str(self.store.memory_path),
                "-s",
                str(self.store.embeddings_path),
                "-s",
                query_file,
                "-g",
                "run_query_json",
                "-t",
                "halt",
            ]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=5.0, check=False)
            if completed.returncode != 0:
                raise SymbolicMemoryError("Prolog memory query failed")
            try:
                result = json.loads(completed.stdout)
            except json.JSONDecodeError as error:
                raise SymbolicMemoryError("Prolog memory query returned invalid JSON") from error
            if not isinstance(result, dict):
                raise SymbolicMemoryError("Prolog memory query returned an invalid shape")
            return result
        finally:
            os.unlink(query_file)

    @staticmethod
    def _query_file(payload: dict[str, object]) -> str:
        def term(value: object) -> str:
            if isinstance(value, str):
                return json.dumps(value, ensure_ascii=False)
            if isinstance(value, list):
                return "[" + ",".join(term(item) if isinstance(item, str) else f"{float(item):.12g}" for item in value) + "]"
            return str(value)

        lines = [
            f"query_text({term(payload['query'])}).",
            f"query_tokens({term(payload['tokens'])}).",
            f"query_scope({term(payload['scope'])}).",
            f"query_limit({payload['limit']}).",
            f"query_now({payload['now']}).",
            f"query_vector({term(payload['vector'])}).",
            f"query_model({term(payload['model'])}).",
        ]
        fd, path = tempfile.mkstemp(prefix="zara-memory-query-", suffix=".pl")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        return path
