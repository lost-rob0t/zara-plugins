from __future__ import annotations

import json
import math
import os
import re
import selectors
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable

from .domain import ExpertError, _is_registered_predicate_capability


_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_PREDICATE_RE = re.compile(r"^[a-z][a-zA-Z0-9_]{0,63}$")
_VARIABLE_RE = re.compile(r"^[A-Z_][a-zA-Z0-9_]{0,63}$")
_MAX_ARGUMENTS = 16


class SwiplBackend:
    def __init__(self, program: str = "swipl", *, output_limit: int = 65536) -> None:
        if isinstance(output_limit, bool) or not isinstance(output_limit, int) or output_limit <= 0:
            raise ValueError("output_limit must be a positive integer")
        self.program = program
        self.output_limit = output_limit

    @classmethod
    def available(cls, program: str = "swipl") -> bool:
        return shutil.which(program) is not None

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        operation = request.get("operation")
        if operation not in {"query", "explain"}:
            raise ExpertError(f"unsupported expert operation: {operation!r}")

        capability = request.get("capability")
        if not _is_registered_predicate_capability(capability):
            raise ExpertError("backend requires a registered predicate capability")
        namespace = request.get("namespace")
        if namespace != capability.namespace:
            raise ExpertError("registered predicate capability namespace mismatch")

        timeout, max_results = self._validate_bounds(
            request["timeout_seconds"],
            request["max_results"],
        )
        source_files = [*request.get("knowledge_bases", ()), *request.get("state_files", ())]
        return self._run_registered(
            namespace=namespace,
            predicate=capability.predicate,
            arity=capability.arity,
            operation=operation,
            arguments=request.get("arguments"),
            source_files=source_files,
            timeout=timeout,
            max_results=max_results,
        )

    def run_core_binding(
        self,
        binding: Any,
        *,
        operation: str,
        arguments: Any,
        knowledge_bases: Iterable[str | Path],
        state_files: Iterable[str | Path],
        timeout_seconds: float,
        max_results: int,
    ) -> dict[str, Any]:
        """Execute one binding selected by Zara Core's isolated authority owner.

        This is a child-side adapter seam for ``RegisteredPredicateBinding``. The
        caller cannot supply a raw predicate through the plugin request path: the
        predicate identity comes from the Core-owned binding object passed into
        the isolated executor. This method does not register, mint, reload, or
        select bindings and therefore is not an authority owner.
        """

        if operation not in {"query", "explain"}:
            raise ExpertError(f"unsupported expert operation: {operation!r}")
        namespace = getattr(binding, "namespace", None)
        predicate = getattr(binding, "predicate", None)
        arity = getattr(binding, "arity", None)
        self._validate_binding_identity(namespace, predicate, arity)
        timeout, max_results = self._validate_bounds(timeout_seconds, max_results)
        source_files = [*knowledge_bases, *state_files]
        return self._run_registered(
            namespace=namespace,
            predicate=predicate,
            arity=arity,
            operation=operation,
            arguments=arguments,
            source_files=source_files,
            timeout=timeout,
            max_results=max_results,
        )

    @staticmethod
    def _validate_binding_identity(namespace: Any, predicate: Any, arity: Any) -> None:
        if not isinstance(namespace, str) or not _NAMESPACE_RE.fullmatch(namespace):
            raise ExpertError("Core predicate binding namespace is invalid")
        if not isinstance(predicate, str) or not _PREDICATE_RE.fullmatch(predicate):
            raise ExpertError("Core predicate binding predicate is invalid")
        if (
            isinstance(arity, bool)
            or not isinstance(arity, int)
            or arity < 0
            or arity > _MAX_ARGUMENTS
        ):
            raise ExpertError("Core predicate binding arity is invalid")

    @staticmethod
    def _validate_bounds(timeout_value: Any, max_results_value: Any) -> tuple[float, int]:
        if (
            isinstance(timeout_value, bool)
            or not isinstance(timeout_value, (int, float))
            or not math.isfinite(timeout_value)
            or timeout_value <= 0
            or isinstance(max_results_value, bool)
            or not isinstance(max_results_value, int)
            or max_results_value <= 0
        ):
            raise ExpertError("expert execution bounds are invalid")
        return float(timeout_value), max_results_value

    def _run_registered(
        self,
        *,
        namespace: str,
        predicate: str,
        arity: int,
        operation: str,
        arguments: Any,
        source_files: Iterable[str | Path],
        timeout: float,
        max_results: int,
    ) -> dict[str, Any]:
        self._validate_binding_identity(namespace, predicate, arity)
        goal = self._build_registered_goal(predicate, arity, arguments)

        command = [self.program, "-q", "-f", "none"]
        for source in source_files:
            path = Path(source)
            if path.exists() and path.stat().st_size:
                command.extend(("-s", str(path)))
        command.extend(("-g", self._driver_goal(), "-t", "halt"))

        environment = os.environ.copy()
        environment.update(
            ZARA_EXPERT_GOAL=goal,
            ZARA_EXPERT_LIMIT=str(max_results),
            ZARA_EXPERT_EXPLAIN="1" if operation == "explain" else "0",
        )
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise ExpertError(f"SWI-Prolog executable not found: {self.program}") from exc

        stdout, stderr = self._communicate_bounded(process, timeout)
        if process.returncode != 0:
            detail = " ".join(stderr.decode("utf-8", errors="replace").split())[:512]
            raise ExpertError(f"SWI-Prolog failed with exit {process.returncode}: {detail}")
        try:
            payload = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExpertError("SWI-Prolog returned invalid structured output") from exc
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise ExpertError("SWI-Prolog returned an invalid expert result")
        return payload

    @classmethod
    def _build_goal(cls, capability: Any, arguments: Any) -> str:
        if not _is_registered_predicate_capability(capability):
            raise ExpertError("backend requires a registered predicate capability")
        return cls._build_registered_goal(capability.predicate, capability.arity, arguments)

    @classmethod
    def _build_registered_goal(cls, predicate: str, arity: int, arguments: Any) -> str:
        cls._validate_binding_identity("registered", predicate, arity)
        if not isinstance(arguments, list):
            raise ExpertError("invalid expert argument descriptor")
        if arity != len(arguments):
            raise ExpertError(
                f"expert predicate arity mismatch: registered {arity}, received {len(arguments)}"
            )
        if not arguments:
            return predicate
        encoded = ",".join(cls._encode_argument(argument) for argument in arguments)
        return f"{predicate}({encoded})"

    @staticmethod
    def _encode_argument(argument: Any) -> str:
        if argument is None:
            return "@(null)"
        if argument is True:
            return "true"
        if argument is False:
            return "false"
        if isinstance(argument, int):
            return str(argument)
        if isinstance(argument, float):
            if not math.isfinite(argument):
                raise ExpertError("expert numeric argument must be finite")
            return repr(argument)
        if isinstance(argument, str):
            escaped = argument.replace("\\", "\\\\").replace("'", "\\'")
            return f"'{escaped}'"
        if isinstance(argument, dict) and set(argument) == {"var"}:
            variable = argument["var"]
            if not isinstance(variable, str) or not _VARIABLE_RE.fullmatch(variable):
                raise ExpertError("invalid expert variable descriptor")
            return variable
        raise ExpertError("unsupported expert argument descriptor")

    def _communicate_bounded(self, process: subprocess.Popen, timeout: float) -> tuple[bytes, bytes]:
        stdout = bytearray()
        stderr = bytearray()
        streams = ((process.stdout, stdout), (process.stderr, stderr))
        selector = selectors.DefaultSelector()
        for stream, buffer in streams:
            if stream is not None:
                selector.register(stream, selectors.EVENT_READ, buffer)

        deadline = time.monotonic() + timeout
        try:
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._stop(process)
                    raise ExpertError(f"expert query exceeded {timeout:.2f}s timeout")
                for key, _ in selector.select(timeout=min(0.1, remaining)):
                    chunk = os.read(key.fd, min(4096, self.output_limit + 1))
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    buffer = key.data
                    buffer.extend(chunk)
                    if len(buffer) > self.output_limit:
                        self._stop(process)
                        raise ExpertError("expert Prolog output exceeded configured limit")

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._stop(process)
                raise ExpertError(f"expert query exceeded {timeout:.2f}s timeout")
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired as exc:
                self._stop(process)
                raise ExpertError(f"expert query exceeded {timeout:.2f}s timeout") from exc
        finally:
            selector.close()
            for stream, _ in streams:
                if stream is not None:
                    stream.close()
        return bytes(stdout), bytes(stderr)

    @staticmethod
    def _stop(process: subprocess.Popen) -> None:
        if process.poll() is None:
            process.kill()
        process.wait()

    @staticmethod
    def _driver_goal() -> str:
        return (
            "use_module(library(http/json)),"
            "getenv('ZARA_EXPERT_GOAL', Atom),"
            "getenv('ZARA_EXPERT_LIMIT', LimitAtom),"
            "atom_number(LimitAtom, Limit),"
            "read_term_from_atom(Atom, Goal, []),"
            "findnsols(Limit, Goal, Goal, Solutions),"
            "maplist(term_string, Solutions, Strings),"
            "getenv('ZARA_EXPERT_EXPLAIN', Explain),"
            "(Explain='1' -> Trace=Strings ; Trace=[]),"
            "json_write_dict(current_output, _{ok:true,results:Strings,trace:Trace})"
        )
