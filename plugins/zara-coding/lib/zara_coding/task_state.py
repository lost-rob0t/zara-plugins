from __future__ import annotations

import json
import select
import subprocess
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Callable, TextIO

from .domain import CodingError


ProcessFactory = Callable[..., subprocess.Popen[str]]
ReadinessWaiter = Callable[[TextIO, float], bool]


def _default_readiness_waiter(stream: TextIO, timeout: float) -> bool:
    try:
        ready, _, _ = select.select((stream,), (), (), timeout)
    except (OSError, TypeError, ValueError):
        return True
    return bool(ready)


class TaskStateSession:
    MAX_ID_CHARS = 128
    MAX_GOAL_CHARS = 4096
    MAX_ITEM_CHARS = 1024
    MAX_LIST_ITEMS = 64
    MAX_DETAIL_CHARS = 4096
    MAX_RESPONSE_CHARS = 131072
    MAX_RESPONSE_TIMEOUT_SECONDS = 60.0
    EVIDENCE_STATUSES = frozenset({"failed", "passed"})
    RESPONSE_STATUSES = frozenset({"ok", "rejected"})

    def __init__(
        self,
        driver: Path,
        *,
        executable: str = "swipl",
        process_factory: ProcessFactory | None = None,
        response_timeout_seconds: float = 5.0,
        readiness_waiter: ReadinessWaiter | None = None,
    ) -> None:
        if (
            not isinstance(executable, str)
            or not executable.strip()
            or any(character in executable for character in ("\x00", "\n", "\r"))
        ):
            raise ValueError("executable must be non-empty single-line text without NUL")
        if (
            isinstance(response_timeout_seconds, bool)
            or not isinstance(response_timeout_seconds, (int, float))
            or not 0 < response_timeout_seconds <= self.MAX_RESPONSE_TIMEOUT_SECONDS
        ):
            raise ValueError(
                f"response_timeout_seconds must be greater than zero and at most {self.MAX_RESPONSE_TIMEOUT_SECONDS}"
            )
        self.driver = Path(driver).expanduser().resolve()
        self.executable = executable
        self.response_timeout_seconds = float(response_timeout_seconds)
        self._process_factory = process_factory or subprocess.Popen
        self._readiness_waiter = readiness_waiter or _default_readiness_waiter
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
            if self._process is not None:
                raise CodingError("zara-coding task-state Prolog process exited unexpectedly")
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
            self._terminate_process(process)

    def status(self) -> dict[str, object]:
        return self._request({"op": "status"})

    def create_task(
        self,
        task_id: str,
        *,
        goal: str,
        repository: Mapping[str, str] | None = None,
        constraints: Sequence[str] = (),
        dependencies: Sequence[str] = (),
        completion_criteria: Sequence[str] = (),
    ) -> dict[str, object]:
        command = {
            "op": "create",
            "task_id": self._bounded_string(task_id, "task_id", self.MAX_ID_CHARS),
            "goal": self._bounded_string(goal, "goal", self.MAX_GOAL_CHARS),
            "repository": self._bounded_repository(repository),
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
        evidence_status = self._bounded_string(status, "status", self.MAX_ITEM_CHARS)
        if evidence_status not in self.EVIDENCE_STATUSES:
            allowed = ", ".join(sorted(self.EVIDENCE_STATUSES))
            raise ValueError(f"status must be one of: {allowed}")
        return self._request(
            {
                "op": "record_evidence",
                "task_id": self._bounded_string(task_id, "task_id", self.MAX_ID_CHARS),
                "kind": self._bounded_string(kind, "kind", self.MAX_ITEM_CHARS),
                "status": evidence_status,
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
            except (BrokenPipeError, OSError) as exc:
                self._fail_protocol(process, "zara-coding task-state protocol failed", exc)
            if not self._readiness_waiter(process.stdout, self.response_timeout_seconds):
                self._fail_protocol(process, "zara-coding task-state response timed out")
            try:
                response_line = process.stdout.readline(self.MAX_RESPONSE_CHARS + 1)
            except OSError as exc:
                self._fail_protocol(process, "zara-coding task-state protocol failed", exc)
            if not response_line:
                self._fail_protocol(process, "zara-coding task-state Prolog process closed the protocol")
            if len(response_line) > self.MAX_RESPONSE_CHARS:
                self._fail_protocol(process, "zara-coding task-state response exceeds size limit")
            try:
                response = json.loads(response_line)
            except json.JSONDecodeError as exc:
                self._fail_protocol(process, "zara-coding task-state returned malformed JSON", exc)
            if not isinstance(response, dict) or not isinstance(response.get("status"), str):
                self._fail_protocol(process, "zara-coding task-state returned malformed response")
            if response["status"] not in self.RESPONSE_STATUSES:
                self._fail_protocol(process, "zara-coding task-state returned unknown status")
            return response

    @classmethod
    def _fail_protocol(
        cls,
        process: subprocess.Popen[str],
        message: str,
        cause: BaseException | None = None,
    ) -> None:
        cls._terminate_process(process)
        error = CodingError(message)
        if cause is not None:
            raise error from cause
        raise error

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    @classmethod
    def _bounded_repository(cls, repository: Mapping[str, str] | None) -> dict[str, str] | None:
        if repository is None:
            return None
        if not isinstance(repository, Mapping):
            raise ValueError("repository must be a mapping")
        if set(repository) != {"root", "head", "branch"}:
            raise ValueError("repository must contain exactly root, head, and branch")
        return {
            "root": cls._bounded_string(repository["root"], "repository.root", cls.MAX_GOAL_CHARS),
            "head": cls._bounded_string(repository["head"], "repository.head", cls.MAX_ID_CHARS),
            "branch": cls._bounded_string(repository["branch"], "repository.branch", cls.MAX_ITEM_CHARS),
        }

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
