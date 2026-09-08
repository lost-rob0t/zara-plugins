from __future__ import annotations

import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class ExpertError(RuntimeError):
    pass


_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_PREDICATE_RE = re.compile(r"^[a-z][a-zA-Z0-9_]{0,63}$")
_VARIABLE_RE = re.compile(r"^[A-Z_][a-zA-Z0-9_]{0,63}$")
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
_MAX_ARGUMENTS = 16
_MAX_ARGUMENT_TEXT = 4096


class ExpertHost:
    def __init__(
        self,
        backend: Any,
        *,
        state_root: Path,
        query_timeout_seconds: float = 1.0,
        max_results: int = 16,
    ) -> None:
        if (
            isinstance(query_timeout_seconds, bool)
            or not isinstance(query_timeout_seconds, (int, float))
        ):
            raise ValueError("query_timeout_seconds must be a finite positive number")
        timeout = float(query_timeout_seconds)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("query_timeout_seconds must be a finite positive number")
        if isinstance(max_results, bool) or not isinstance(max_results, int) or max_results <= 0:
            raise ValueError("max_results must be a positive integer")
        self._backend = backend
        self._state_root = Path(state_root)
        self._state_root.mkdir(parents=True, exist_ok=True)
        self._query_timeout_seconds = timeout
        self._max_results = max_results
        self._knowledge_bases: dict[str, tuple[str, ...]] = {}
        self._predicates: dict[str, dict[str, int]] = {}

    def register(
        self,
        namespace: str,
        knowledge_bases: Iterable[Path],
        *,
        predicates: Mapping[str, int] | None = None,
    ) -> None:
        namespace = self._validate_namespace(namespace)
        files = tuple(str(Path(path).resolve()) for path in knowledge_bases)
        capabilities: dict[str, int] = {}
        for predicate, arity in (predicates or {}).items():
            predicate = self._validate_predicate(predicate)
            if isinstance(arity, bool) or not isinstance(arity, int) or arity < 0 or arity > _MAX_ARGUMENTS:
                raise ExpertError(f"invalid arity for predicate {predicate!r}")
            capabilities[predicate] = arity
        self._knowledge_bases[namespace] = files
        self._predicates[namespace] = capabilities
        self.state_files(namespace)

    def query(self, namespace: str, predicate: str, arguments: Sequence[Any] | None = None) -> dict[str, Any]:
        return self._run(namespace, "query", predicate, arguments)

    def explain(self, namespace: str, predicate: str, arguments: Sequence[Any] | None = None) -> dict[str, Any]:
        return self._run(namespace, "explain", predicate, arguments)

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

    def _run(
        self,
        namespace: str,
        operation: str,
        predicate: str,
        arguments: Sequence[Any] | None,
    ) -> dict[str, Any]:
        namespace = self._validate_namespace(namespace)
        if namespace not in self._knowledge_bases:
            raise ExpertError(f"expert namespace {namespace!r} is not registered")
        predicate = self._validate_predicate(predicate)
        capabilities = self._predicates.get(namespace, {})
        if predicate not in capabilities:
            raise ExpertError(f"predicate {predicate!r} is not registered for namespace {namespace!r}")
        normalized_arguments = self._validate_arguments(arguments)
        arity = capabilities[predicate]
        if len(normalized_arguments) != arity:
            raise ExpertError(
                f"predicate {predicate!r} arity mismatch: registered {arity}, received {len(normalized_arguments)}"
            )
        session_path, persistent_path = self.state_files(namespace)
        request = {
            "namespace": namespace,
            "operation": operation,
            "predicate": predicate,
            "arity": arity,
            "arguments": normalized_arguments,
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
    def _validate_predicate(predicate: str) -> str:
        if not isinstance(predicate, str) or not _PREDICATE_RE.fullmatch(predicate):
            raise ExpertError("invalid expert predicate")
        return predicate

    @classmethod
    def _validate_arguments(cls, arguments: Sequence[Any] | None) -> list[Any]:
        if arguments is None:
            return []
        if isinstance(arguments, (str, bytes)) or not isinstance(arguments, (list, tuple)):
            raise ExpertError("expert arguments must be a list")
        if len(arguments) > _MAX_ARGUMENTS:
            raise ExpertError("too many expert arguments")
        return [cls._validate_argument(argument) for argument in arguments]

    @staticmethod
    def _validate_argument(argument: Any) -> Any:
        if argument is None or isinstance(argument, bool):
            return argument
        if isinstance(argument, int):
            return argument
        if isinstance(argument, float):
            if not math.isfinite(argument):
                raise ExpertError("expert numeric argument must be finite")
            return argument
        if isinstance(argument, str):
            if len(argument) > _MAX_ARGUMENT_TEXT or "\x00" in argument:
                raise ExpertError("expert text argument is too large or malformed")
            return argument
        if isinstance(argument, dict) and set(argument) == {"var"}:
            variable = argument["var"]
            if not isinstance(variable, str) or not _VARIABLE_RE.fullmatch(variable):
                raise ExpertError("invalid expert variable descriptor")
            return {"var": variable}
        raise ExpertError("expert argument must be a scalar or variable descriptor")

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
