from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable


class ExpertError(RuntimeError):
    pass


_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_TERM_RE = re.compile(r"^[a-z][a-zA-Z0-9_]*(?:\([^\n;:.]*\))?$")
_GROUND_FACT_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\([a-z0-9_' -]+(?:,[a-z0-9_' -]+)*\))?$")
_FORBIDDEN = (
    ":-",
    ";",
    "shell(",
    "halt",
    "assert(",
    "asserta(",
    "assertz(",
    "retract(",
    "consult(",
    "ensure_loaded(",
    "use_module(",
    "open(",
    "process_create(",
)


class ExpertHost:
    def __init__(
        self,
        backend: Any,
        *,
        state_root: Path,
        query_timeout_seconds: float = 1.0,
        max_results: int = 16,
    ) -> None:
        if query_timeout_seconds <= 0:
            raise ValueError("query_timeout_seconds must be positive")
        if max_results <= 0:
            raise ValueError("max_results must be positive")
        self._backend = backend
        self._state_root = Path(state_root)
        self._state_root.mkdir(parents=True, exist_ok=True)
        self._query_timeout_seconds = float(query_timeout_seconds)
        self._max_results = int(max_results)
        self._knowledge_bases: dict[str, tuple[str, ...]] = {}

    def register(self, namespace: str, knowledge_bases: Iterable[Path]) -> None:
        namespace = self._validate_namespace(namespace)
        files = tuple(str(Path(path).resolve()) for path in knowledge_bases)
        self._knowledge_bases[namespace] = files
        self.state_files(namespace)

    def query(self, namespace: str, goal: str) -> dict[str, Any]:
        return self._run(namespace, "query", goal)

    def explain(self, namespace: str, goal: str) -> dict[str, Any]:
        return self._run(namespace, "explain", goal)

    def assert_fact(self, namespace: str, fact: str, *, persistent: bool = False) -> bool:
        namespace = self._validate_namespace(namespace)
        normalized = self._validate_fact(fact)
        session_path, persistent_path = self.state_files(namespace)
        target = persistent_path if persistent else session_path
        facts = self._read_facts(target)
        line = f"{normalized}."
        if line in facts:
            return False
        facts.append(line)
        self._atomic_write(target, facts)
        return True

    def retract_fact(self, namespace: str, fact: str, *, persistent: bool = False) -> bool:
        namespace = self._validate_namespace(namespace)
        normalized = self._validate_fact(fact)
        session_path, persistent_path = self.state_files(namespace)
        target = persistent_path if persistent else session_path
        facts = self._read_facts(target)
        line = f"{normalized}."
        try:
            facts.remove(line)
        except ValueError:
            return False
        self._atomic_write(target, facts)
        return True

    def state_files(self, namespace: str) -> tuple[Path, Path]:
        namespace = self._validate_namespace(namespace)
        root = self._state_root / namespace
        root.mkdir(parents=True, exist_ok=True)
        session_path = root / "session.pl"
        persistent_path = root / "persistent.pl"
        for path in (session_path, persistent_path):
            if not path.exists():
                self._atomic_write(path, [])
        return session_path, persistent_path

    def _run(self, namespace: str, operation: str, goal: str) -> dict[str, Any]:
        namespace = self._validate_namespace(namespace)
        if namespace not in self._knowledge_bases:
            raise ExpertError(f"expert namespace {namespace!r} is not registered")
        goal = self._validate_query(goal)
        session_path, persistent_path = self.state_files(namespace)
        request = {
            "namespace": namespace,
            "operation": operation,
            "goal": goal,
            "knowledge_bases": self._knowledge_bases[namespace],
            "state_files": (str(session_path), str(persistent_path)),
            "timeout_seconds": self._query_timeout_seconds,
            "max_results": self._max_results,
        }
        try:
            result = self._backend.run(request)
        except ExpertError:
            raise
        except Exception as exc:
            raise ExpertError(f"{namespace}: backend failure: {exc}") from exc
        if not isinstance(result, dict):
            raise ExpertError(f"{namespace}: backend returned a non-object result")
        return result

    @staticmethod
    def _validate_namespace(namespace: str) -> str:
        if not isinstance(namespace, str) or not _NAME_RE.fullmatch(namespace):
            raise ExpertError("invalid expert namespace")
        return namespace

    @staticmethod
    def _validate_query(goal: str) -> str:
        if not isinstance(goal, str):
            raise ExpertError("query must be text")
        normalized = goal.strip()
        lowered = normalized.lower()
        if not normalized or any(token in lowered for token in _FORBIDDEN):
            raise ExpertError("unsafe or malformed Prolog query")
        if not _TERM_RE.fullmatch(normalized):
            raise ExpertError("unsafe or malformed Prolog query")
        return normalized

    @staticmethod
    def _validate_fact(fact: str) -> str:
        if not isinstance(fact, str):
            raise ExpertError("fact must be text")
        normalized = fact.strip().removesuffix(".").strip()
        lowered = normalized.lower()
        if not normalized or any(token in lowered for token in _FORBIDDEN):
            raise ExpertError("fact must be a safe ground term")
        if not _GROUND_FACT_RE.fullmatch(normalized):
            raise ExpertError("fact must be a safe ground term")
        return normalized

    @staticmethod
    def _read_facts(path: Path) -> list[str]:
        if not path.exists():
            return []
        return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    @staticmethod
    def _atomic_write(path: Path, lines: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                if lines:
                    handle.write("\n".join(lines) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
