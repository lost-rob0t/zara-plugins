from __future__ import annotations

import json
import math
import os
import selectors
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .domain import ExpertError


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

        timeout_value = request["timeout_seconds"]
        max_results_value = request["max_results"]
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
        timeout = float(timeout_value)
        max_results = max_results_value
        goal = str(request["goal"])
        source_files = [*request.get("knowledge_bases", ()), *request.get("state_files", ())]

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
