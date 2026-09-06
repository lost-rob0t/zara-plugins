from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Callable

from .domain import CodingError


ProcessFactory = Callable[..., subprocess.Popen[str]]


class TaskStateSession:
    MAX_ID_CHARS = 128
    MAX_GOAL_CHARS = 4096
    MAX_ITEM_CHARS = 1024
    MAX_LIST_ITEMS = 64
    MAX_DETAIL_CHARS = 4096
    MAX_RESPONSE_CHARS = 131072

    def __init__(
        self,
        driver: Path,
        *,
        executable: str = "swipl",
        process_factory: ProcessFactory | None = None,
    ) -> None:
        if not executable:
            raise ValueError("executable must be non-empty")
        self.driver = Path(driver).expanduser().resolve()
        self.executable = executable
        self._process_factory = process_factory or subprocess.Popen
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.RLock()

    @property
    def running(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            try:
                process = self._process_factory(
                    [self.executable, "-q", "-s", str(self.driver), "-g", "zara_coding_task_state:serve"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    shell=False,
                )
            except (FileNotFoundError, OSError) as exc:
                raise CodingError("zara-coding task-state Prolog process could not start") from exc
            if process.stdin is None or process.stdout is None:
                process.terminate()
                raise CodingError("zara-coding task-state Prolog process lacks protocol pipes")
            self._process = process

    def stop(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            if process is None or process.poll() is not None:
                return
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)

    def create_task(
        self,
        task_id: str,
        *,
        goal: str,
        constraints: Sequence[str] = (),
        dependencies: Sequence[str] = (),
        completion_criteria: Sequence[str] = (),
    ) -> dict[str, object]:
        command = {
            "op": "create",
            "task_id": self._bounded_string(task_id, "task_id", self.MAX_ID_CHARS),
            "goal": self._bounded_string(goal, "goal", self.MAX_GOAL_CHARS),
            "constraints": self._bounded_strings(constraints, "constraints"),
            "dependencies": self._bounded_strings(dependencies, "dependencies"),
            "completion_criteria": self._bounded_strings(completion_criteria, "completion_criteria"),
        }
        return self._request(command)

    def get_task(self, task_id: str) -> dict[str, object]:
        return self._request(
            {"op": "get", "task_id": self._bounded_string(task_id, "task_id", self.MAX_ID_CHARS)}
        )

    def record_evidence(self, task_id: str, *, kind: str, status: str, detail: str) -> dict[str, object]:
        return self._request(
            {
                "op": "record_evidence",
                "task_id": self._bounded_string(task_id, "task_id", self.MAX_ID_CHARS),
                "kind": self._bounded_string(kind, "kind", self.MAX_ITEM_CHARS),
                "status": self._bounded_string(status, "status", self.MAX_ITEM_CHARS),
                "detail": self._bounded_string(detail, "detail", self.MAX_DETAIL_CHARS),
            }
        )

    def complete_task(self, task_id: str) -> dict[str, object]:
        return self._request(
            {"op": "complete", "task_id": self._bounded_string(task_id, "task_id", self.MAX_ID_CHARS)}
        )

    def _request(self, command: dict[str, object]) -> dict[str, object]:
        with self._lock:
            self.start()
            process = self._process
            if process is None or process.stdin is None or process.stdout is None:
                raise CodingError("zara-coding task-state Prolog session is unavailable")
            if process.poll() is not None:
                raise CodingError("zara-coding task-state Prolog process exited unexpectedly")
            wire = json.dumps(command, separators=(",", ":"), sort_keys=True)
            try:
                process.stdin.write(wire + "\n")
                process.stdin.flush()
                response_line = process.stdout.readline()
            except (BrokenPipeError, OSError) as exc:
                raise CodingError("zara-coding task-state protocol failed") from exc
            if not response_line:
                raise CodingError("zara-coding task-state Prolog process closed the protocol")
            if len(response_line) > self.MAX_RESPONSE_CHARS:
                raise CodingError("zara-coding task-state response exceeds size limit")
            try:
                response = json.loads(response_line)
            except json.JSONDecodeError as exc:
                raise CodingError("zara-coding task-state returned malformed JSON") from exc
            if not isinstance(response, dict) or not isinstance(response.get("status"), str):
                raise CodingError("zara-coding task-state returned malformed response")
            return response

    @classmethod
    def _bounded_string(cls, value: str, name: str, maximum: int) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
        if len(value) > maximum:
            raise ValueError(f"{name} exceeds {maximum} character limit")
        return value

    @classmethod
    def _bounded_strings(cls, values: Sequence[str], name: str) -> list[str]:
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise ValueError(f"{name} must be a sequence of strings")
        if len(values) > cls.MAX_LIST_ITEMS:
            raise ValueError(f"{name} exceeds {cls.MAX_LIST_ITEMS} item limit")
        return [cls._bounded_string(value, name, cls.MAX_ITEM_CHARS) for value in values]
