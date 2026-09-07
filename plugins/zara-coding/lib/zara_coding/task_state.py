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
Request = Callable[[dict[str, object]], dict[str, object]]


def _default_readiness_waiter(stream: TextIO, timeout: float) -> bool:
    try:
        ready, _, _ = select.select((stream,), (), (), timeout)
    except (OSError, TypeError, ValueError):
        return True
    return bool(ready)


class _TaskStateProtocol:
    RESPONSE_STATUSES = frozenset({"ok", "rejected"})
    MAX_RESPONSE_CHARS = 131072

    def __init__(
        self,
        driver: Path,
        *,
        executable: str,
        process_factory: ProcessFactory,
        response_timeout_seconds: float,
        readiness_waiter: ReadinessWaiter,
    ) -> None:
        self.driver = driver
        self.executable = executable
        self.response_timeout_seconds = response_timeout_seconds
        self._process_factory = process_factory
        self._readiness_waiter = readiness_waiter
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

    def caller_request(self, command: dict[str, object]) -> dict[str, object]:
        if command.get("op") == "record_verifier_evidence" or command.get("provenance") == "verifier":
            raise PermissionError("verifier authority is not available through the generic task-state protocol")
        return self._request(command)

    def verifier_evidence_request(self, command: dict[str, object]) -> dict[str, object]:
        trusted = dict(command)
        trusted["op"] = "record_verifier_evidence"
        trusted.pop("provenance", None)
        return self._request(trusted)

    def fence(self, message: str) -> None:
        process = self._process
        if process is not None:
            self._fail_protocol(process, message)
        raise CodingError(message)

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


class TaskStateSession:
    MAX_ID_CHARS = 128
    MAX_GOAL_CHARS = 4096
    MAX_ITEM_CHARS = 1024
    MAX_LIST_ITEMS = 64
    MAX_DETAIL_CHARS = 4096
    MAX_RESPONSE_CHARS = _TaskStateProtocol.MAX_RESPONSE_CHARS
    MAX_RESPONSE_TIMEOUT_SECONDS = 60.0
    EVIDENCE_STATUSES = frozenset({"failed", "passed"})
    RESPONSE_STATUSES = _TaskStateProtocol.RESPONSE_STATUSES

    def __init__(
        self,
        driver: Path,
        *,
        executable: str = "swipl",
        process_factory: ProcessFactory | None = None,
        response_timeout_seconds: float = 5.0,
        readiness_waiter: ReadinessWaiter | None = None,
        _request: Request | None = None,
        _start: Callable[[], None] | None = None,
        _stop: Callable[[], None] | None = None,
        _running: Callable[[], bool] | None = None,
        _fence: Callable[[str], None] | None = None,
    ) -> None:
        driver_path, executable_text, timeout, factory, waiter = self._validated_runtime(
            driver,
            executable=executable,
            process_factory=process_factory,
            response_timeout_seconds=response_timeout_seconds,
            readiness_waiter=readiness_waiter,
        )
        if _request is None:
            protocol = _TaskStateProtocol(
                driver_path,
                executable=executable_text,
                process_factory=factory,
                response_timeout_seconds=timeout,
                readiness_waiter=waiter,
            )
            _request = protocol.caller_request
            _start = protocol.start
            _stop = protocol.stop
            _running = lambda: protocol.running
            _fence = protocol.fence
        assert _start is not None and _stop is not None and _running is not None and _fence is not None
        self.driver = driver_path
        self.executable = executable_text
        self.response_timeout_seconds = timeout
        self._request_command = _request
        self._start_session = _start
        self._stop_session = _stop
        self._running_session = _running
        self._fence_session = _fence
        self._lock = threading.RLock()

    @property
    def running(self) -> bool:
        return self._running_session()

    def start(self) -> None:
        self._start_session()

    def stop(self) -> None:
        self._stop_session()

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
        return self._request(
            {
                "op": "create",
                "task_id": self._bounded_string(task_id, "task_id", self.MAX_ID_CHARS),
                "goal": self._bounded_string(goal, "goal", self.MAX_GOAL_CHARS),
                "repository": self._bounded_repository(repository),
                "constraints": self._bounded_strings(constraints, "constraints"),
                "dependencies": self._bounded_strings(dependencies, "dependencies"),
                "completion_criteria": self._bounded_strings(completion_criteria, "completion_criteria"),
            }
        )

    def get_task(self, task_id: str) -> dict[str, object]:
        return self._request(
            {"op": "get", "task_id": self._bounded_string(task_id, "task_id", self.MAX_ID_CHARS)}
        )

    def record_evidence(self, task_id: str, *, kind: str, status: str, detail: str) -> dict[str, object]:
        evidence_status = self._bounded_evidence_status(status)
        if evidence_status == "passed":
            raise ValueError("passing task evidence is verifier-owned")
        return self._request(
            {
                "op": "record_evidence",
                "task_id": self._bounded_string(task_id, "task_id", self.MAX_ID_CHARS),
                "kind": self._bounded_string(kind, "kind", self.MAX_ITEM_CHARS),
                "status": evidence_status,
                "detail": self._bounded_string(detail, "detail", self.MAX_DETAIL_CHARS),
            }
        )

    def complete_task(
        self,
        task_id: str,
        *,
        expected_repository: Mapping[str, str] | None = None,
        repository_validator: Callable[[Mapping[str, str]], bool] | None = None,
    ) -> dict[str, object]:
        bounded_task_id = self._bounded_string(task_id, "task_id", self.MAX_ID_CHARS)
        with self._lock:
            bounded_repository = None
            if expected_repository is not None or repository_validator is not None:
                if expected_repository is None or repository_validator is None:
                    raise ValueError("expected_repository and repository_validator must be provided together")
                bounded_repository = self._bounded_repository(expected_repository)
                if bounded_repository is None or not repository_validator(bounded_repository):
                    return {"status": "rejected", "reason": "repository-snapshot-stale"}

            response = self._request({"op": "complete", "task_id": bounded_task_id})
            if response.get("status") != "ok" or bounded_repository is None or repository_validator is None:
                return response

            try:
                repository_current = repository_validator(bounded_repository)
            except Exception as exc:
                self._invalidate_completion_or_fence(bounded_task_id)
                raise CodingError("zara-coding repository validation failed after completion") from exc

            if repository_current:
                return response

            self._invalidate_completion_or_fence(bounded_task_id)
            return {"status": "rejected", "reason": "repository-snapshot-stale"}

    def _invalidate_completion_or_fence(self, task_id: str) -> None:
        response = self._request({"op": "invalidate_completion", "task_id": task_id})
        if response.get("status") == "ok":
            return
        self._fence_session("zara-coding task-state could not invalidate stale completion")

    def _request(self, command: dict[str, object]) -> dict[str, object]:
        if command.get("op") == "record_verifier_evidence" or command.get("provenance") == "verifier":
            raise PermissionError("verifier authority is not available through the generic task-state protocol")
        return self._request_command(command)

    @classmethod
    def _validated_runtime(
        cls,
        driver: Path,
        *,
        executable: str,
        process_factory: ProcessFactory | None,
        response_timeout_seconds: float,
        readiness_waiter: ReadinessWaiter | None,
    ) -> tuple[Path, str, float, ProcessFactory, ReadinessWaiter]:
        if not isinstance(executable, str) or not executable.strip() or any(
            character in executable for character in ("\x00", "\n", "\r")
        ):
            raise ValueError("executable must be non-empty single-line text without NUL")
        if (
            isinstance(response_timeout_seconds, bool)
            or not isinstance(response_timeout_seconds, (int, float))
            or not 0 < response_timeout_seconds <= cls.MAX_RESPONSE_TIMEOUT_SECONDS
        ):
            raise ValueError(
                f"response_timeout_seconds must be greater than zero and at most {cls.MAX_RESPONSE_TIMEOUT_SECONDS}"
            )
        return (
            Path(driver).expanduser().resolve(),
            executable,
            float(response_timeout_seconds),
            process_factory or subprocess.Popen,
            readiness_waiter or _default_readiness_waiter,
        )

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
    def _bounded_evidence_status(cls, status: str) -> str:
        evidence_status = cls._bounded_string(status, "status", cls.MAX_ITEM_CHARS)
        if evidence_status not in cls.EVIDENCE_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(cls.EVIDENCE_STATUSES))}")
        return evidence_status

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


class TaskStateVerifier:
    def __init__(self, request: Request) -> None:
        self._record_verifier = request

    def record_evidence(self, task_id: str, *, kind: str, status: str, detail: str) -> dict[str, object]:
        return self._record_verifier(
            {
                "task_id": TaskStateSession._bounded_string(task_id, "task_id", TaskStateSession.MAX_ID_CHARS),
                "kind": TaskStateSession._bounded_string(kind, "kind", TaskStateSession.MAX_ITEM_CHARS),
                "status": TaskStateSession._bounded_evidence_status(status),
                "detail": TaskStateSession._bounded_string(detail, "detail", TaskStateSession.MAX_DETAIL_CHARS),
            }
        )


def create_task_state_interfaces(
    driver: Path,
    *,
    executable: str = "swipl",
    process_factory: ProcessFactory | None = None,
    response_timeout_seconds: float = 5.0,
    readiness_waiter: ReadinessWaiter | None = None,
) -> tuple[TaskStateSession, TaskStateVerifier]:
    driver_path, executable_text, timeout, factory, waiter = TaskStateSession._validated_runtime(
        driver,
        executable=executable,
        process_factory=process_factory,
        response_timeout_seconds=response_timeout_seconds,
        readiness_waiter=readiness_waiter,
    )
    protocol = _TaskStateProtocol(
        driver_path,
        executable=executable_text,
        process_factory=factory,
        response_timeout_seconds=timeout,
        readiness_waiter=waiter,
    )
    session = TaskStateSession(
        driver_path,
        executable=executable_text,
        response_timeout_seconds=timeout,
        _request=protocol.caller_request,
        _start=protocol.start,
        _stop=protocol.stop,
        _running=lambda: protocol.running,
        _fence=protocol.fence,
    )
    verifier = TaskStateVerifier(protocol.verifier_evidence_request)
    return session, verifier
