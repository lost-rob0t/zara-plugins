from __future__ import annotations

import math
import re
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, Sequence


class PiError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str


class Executor(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float,
        cwd: Path | None = None,
    ) -> ExecResult: ...


class SubprocessExecutor:
    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float,
        cwd: Path | None = None,
    ) -> ExecResult:
        try:
            completed = subprocess.run(
                list(argv),
                cwd=str(cwd) if cwd is not None else None,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                shell=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise PiError("tmux operation timed out") from exc
        except OSError as exc:
            raise PiError("tmux operation could not start") from exc
        return ExecResult(
            exit_code=int(completed.returncode),
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


@dataclass(frozen=True)
class PiPolicy:
    allowed_roots: tuple[Path, ...]
    pi_program: str
    tmux_program: str
    bash_program: str
    max_command_bytes: int = 65536
    max_capture_bytes: int = 65536
    max_tmux_lines: int = 2000
    operation_timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not isinstance(self.allowed_roots, tuple) or not self.allowed_roots:
            raise ValueError("allowed_roots must be a non-empty tuple")
        if any(not isinstance(root, (str, Path)) or not str(root) for root in self.allowed_roots):
            raise ValueError("allowed_roots must contain non-empty paths")
        for value, name in (
            (self.pi_program, "pi_program"),
            (self.tmux_program, "tmux_program"),
            (self.bash_program, "bash_program"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        for value, name in (
            (self.max_command_bytes, "max_command_bytes"),
            (self.max_capture_bytes, "max_capture_bytes"),
            (self.max_tmux_lines, "max_tmux_lines"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if (
            isinstance(self.operation_timeout_seconds, bool)
            or not isinstance(self.operation_timeout_seconds, (int, float))
            or not math.isfinite(self.operation_timeout_seconds)
            or self.operation_timeout_seconds <= 0
        ):
            raise ValueError("operation_timeout_seconds must be finite positive")


@dataclass(frozen=True)
class Invocation:
    invocation_id: str
    nonce: str


_SESSION_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,31}\Z")
_INVOCATION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_NONCE_RE = re.compile(r"[0-9a-f]{32}\Z")
_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_OWNER_OPTION = "@zara_pi_owner"
_OWNER_VALUE = "ZARA_PI/1"
_INVOCATION_OPTION = "@zara_pi_invocation"


class TmuxBridge:
    def __init__(
        self,
        policy: PiPolicy,
        *,
        executor: Executor | None = None,
        nonce_factory: Callable[[], str] | None = None,
    ) -> None:
        self.policy = policy
        self.executor = executor or SubprocessExecutor()
        self._nonce_factory = nonce_factory or (lambda: secrets.token_hex(16))
        self._roots = tuple(Path(root).expanduser().resolve() for root in policy.allowed_roots)

    def ensure(self, session_id: str, cwd: Path) -> dict[str, object]:
        session = self._session_name(session_id)
        working_directory = self._validate_cwd(cwd)
        if self._has_session(session):
            self._assert_owner(session)
            return {
                "status": "existing",
                "session_id": session_id,
                "session": session,
                "cwd": str(working_directory),
            }
        created = self._run(
            [
                self.policy.tmux_program,
                "new-session",
                "-d",
                "-s",
                session,
                "-c",
                str(working_directory),
                self.policy.bash_program,
                "--noprofile",
                "--norc",
            ]
        )
        self._require_success(created, "tmux session creation")
        owner = self._run(
            [
                self.policy.tmux_program,
                "set-option",
                "-t",
                session,
                _OWNER_OPTION,
                _OWNER_VALUE,
            ]
        )
        if owner.exit_code != 0:
            self._run([self.policy.tmux_program, "kill-session", "-t", session])
            raise PiError("could not mark tmux session as Zara Pi owned")
        return {
            "status": "created",
            "session_id": session_id,
            "session": session,
            "cwd": str(working_directory),
        }

    def bash(
        self,
        *,
        session_id: str,
        invocation_id: str,
        command: str,
        cwd: Path,
    ) -> dict[str, object]:
        self._validate_invocation(invocation_id)
        if not isinstance(command, str) or not command or "\0" in command:
            raise PiError("bash command must be non-empty text without NUL bytes")
        if len(command.encode("utf-8")) > self.policy.max_command_bytes:
            raise PiError("bash command exceeds configured limit")
        ensured = self.ensure(session_id, cwd)
        session = str(ensured["session"])
        current = self._current_invocation(session)
        if current is not None:
            raise PiError("tmux session already has an active invocation")
        nonce = self._nonce_factory()
        if not isinstance(nonce, str) or _NONCE_RE.fullmatch(nonce) is None:
            raise PiError("invalid internal invocation nonce")
        invocation = Invocation(invocation_id=invocation_id, nonce=nonce)
        persisted = self._run(
            [
                self.policy.tmux_program,
                "set-option",
                "-t",
                session,
                _INVOCATION_OPTION,
                f"{invocation.invocation_id}:{invocation.nonce}",
            ]
        )
        self._require_success(persisted, "tmux invocation registration")
        begin = self._begin_marker(invocation.nonce)
        end = self._end_marker(invocation.nonce)
        payload = (
            f"printf '\\n{begin}\\n'\n"
            f"{command}\n"
            "__zara_pi_exit=$?\n"
            f"printf '\\n{end}:%s\\n' \"$__zara_pi_exit\""
        )
        sent = self._run(
            [self.policy.tmux_program, "send-keys", "-t", session, "-l", payload]
        )
        if sent.exit_code != 0:
            self._clear_invocation(session, best_effort=True)
            raise PiError("could not send Bash command to tmux session")
        entered = self._run(
            [self.policy.tmux_program, "send-keys", "-t", session, "Enter"]
        )
        if entered.exit_code != 0:
            self._clear_invocation(session, best_effort=True)
            raise PiError("could not execute Bash command in tmux session")
        return {
            "status": "accepted",
            "session_id": session_id,
            "session": session,
            "invocation_id": invocation_id,
        }

    def capture(
        self,
        session_id: str,
        *,
        invocation_id: str | None = None,
    ) -> dict[str, object]:
        session = self._session_name(session_id)
        self._assert_owned(session)
        invocation = None
        if invocation_id is not None:
            self._validate_invocation(invocation_id)
            invocation = self._current_invocation(session)
            if invocation is None:
                return {
                    "status": "unknown",
                    "session_id": session_id,
                    "session": session,
                    "invocation_id": invocation_id,
                    "output": "",
                    "truncated": False,
                }
            if invocation.invocation_id != invocation_id:
                raise PiError("stale invocation id")
        captured = self._run(
            [
                self.policy.tmux_program,
                "capture-pane",
                "-p",
                "-J",
                "-S",
                f"-{self.policy.max_tmux_lines}",
                "-t",
                session,
            ]
        )
        self._require_success(captured, "tmux pane capture")
        clean = self._sanitize(captured.stdout)
        if invocation is None:
            output, truncated = self._bound_text(clean)
            return {
                "status": "snapshot",
                "session_id": session_id,
                "session": session,
                "output": output,
                "truncated": truncated,
            }
        begin = self._begin_marker(invocation.nonce)
        end = self._end_marker(invocation.nonce)
        begin_index = clean.rfind(begin)
        end_match = None
        search_start = begin_index + len(begin) if begin_index >= 0 else 0
        end_re = re.compile(re.escape(end) + r":(-?\d+)")
        for match in end_re.finditer(clean, search_start):
            end_match = match
        if end_match is None:
            body = clean[search_start:] if begin_index >= 0 else clean
            output, truncated = self._bound_text(body)
            return {
                "status": "active",
                "session_id": session_id,
                "session": session,
                "invocation_id": invocation_id,
                "output": output.strip("\r\n"),
                "truncated": truncated,
            }
        body_start = search_start
        body = clean[body_start : end_match.start()]
        output, truncated = self._bound_text(body)
        self._clear_invocation(session)
        return {
            "status": "completed",
            "session_id": session_id,
            "session": session,
            "invocation_id": invocation_id,
            "exit_code": int(end_match.group(1)),
            "output": output.strip("\r\n"),
            "truncated": truncated,
            "begin_marker_observed": begin_index >= 0,
        }

    def interrupt(self, session_id: str, invocation_id: str) -> dict[str, object]:
        session = self._session_name(session_id)
        self._validate_invocation(invocation_id)
        self._assert_owned(session)
        current = self._current_invocation(session)
        if current is None or current.invocation_id != invocation_id:
            raise PiError("stale invocation id")
        interrupted = self._run(
            [self.policy.tmux_program, "send-keys", "-t", session, "C-c"]
        )
        self._require_success(interrupted, "tmux interrupt")
        self._clear_invocation(session)
        return {
            "status": "interrupt_sent",
            "session_id": session_id,
            "session": session,
            "invocation_id": invocation_id,
            "terminated_confirmed": False,
        }

    def close(self, session_id: str) -> dict[str, object]:
        session = self._session_name(session_id)
        self._assert_owned(session)
        closed = self._run([self.policy.tmux_program, "kill-session", "-t", session])
        self._require_success(closed, "tmux session close")
        return {
            "status": "closed",
            "session_id": session_id,
            "session": session,
        }

    def _run(self, argv: Sequence[str]) -> ExecResult:
        return self.executor.run(
            argv,
            timeout=float(self.policy.operation_timeout_seconds),
            cwd=None,
        )

    def _has_session(self, session: str) -> bool:
        result = self._run([self.policy.tmux_program, "has-session", "-t", session])
        if result.exit_code == 0:
            return True
        if result.exit_code == 1:
            return False
        raise PiError("tmux session lookup failed")

    def _assert_owned(self, session: str) -> None:
        if not self._has_session(session):
            raise PiError("Zara Pi tmux session does not exist")
        self._assert_owner(session)

    def _assert_owner(self, session: str) -> None:
        owner = self._run(
            [self.policy.tmux_program, "show-options", "-v", "-t", session, _OWNER_OPTION]
        )
        if owner.exit_code != 0 or owner.stdout.strip() != _OWNER_VALUE:
            raise PiError("tmux session is not owned by Zara Pi")

    def _current_invocation(self, session: str) -> Invocation | None:
        result = self._run(
            [
                self.policy.tmux_program,
                "show-options",
                "-v",
                "-t",
                session,
                _INVOCATION_OPTION,
            ]
        )
        if result.exit_code != 0 or not result.stdout.strip():
            return None
        value = result.stdout.strip()
        if ":" not in value:
            raise PiError("tmux invocation metadata is malformed")
        invocation_id, nonce = value.split(":", 1)
        self._validate_invocation(invocation_id)
        if _NONCE_RE.fullmatch(nonce) is None:
            raise PiError("tmux invocation metadata is malformed")
        return Invocation(invocation_id=invocation_id, nonce=nonce)

    def _clear_invocation(self, session: str, *, best_effort: bool = False) -> None:
        result = self._run(
            [
                self.policy.tmux_program,
                "set-option",
                "-u",
                "-t",
                session,
                _INVOCATION_OPTION,
            ]
        )
        if not best_effort:
            self._require_success(result, "tmux invocation cleanup")

    def _validate_cwd(self, cwd: Path) -> Path:
        try:
            resolved = Path(cwd).expanduser().resolve()
        except (TypeError, OSError) as exc:
            raise PiError("cwd must be path-like") from exc
        if not resolved.is_dir():
            raise PiError("cwd must be an existing directory")
        if not any(resolved == root or root in resolved.parents for root in self._roots):
            raise PiError("cwd is outside allowed roots")
        return resolved

    @staticmethod
    def _validate_invocation(invocation_id: str) -> None:
        if not isinstance(invocation_id, str) or _INVOCATION_RE.fullmatch(invocation_id) is None:
            raise PiError("invalid invocation id")

    @staticmethod
    def _session_name(session_id: str) -> str:
        if not isinstance(session_id, str) or _SESSION_RE.fullmatch(session_id) is None:
            raise PiError("invalid tmux session id")
        return f"zara-pi-{session_id}"

    @staticmethod
    def _begin_marker(nonce: str) -> str:
        return f"__ZARA_PI_BEGIN_{nonce}__"

    @staticmethod
    def _end_marker(nonce: str) -> str:
        return f"__ZARA_PI_END_{nonce}__"

    @staticmethod
    def _sanitize(text: str) -> str:
        text = _OSC_RE.sub("", text)
        text = _CSI_RE.sub("", text)
        return _CONTROL_RE.sub("", text)

    def _bound_text(self, text: str) -> tuple[str, bool]:
        encoded = text.encode("utf-8")
        if len(encoded) <= self.policy.max_capture_bytes:
            return text, False
        tail = encoded[-self.policy.max_capture_bytes :]
        return tail.decode("utf-8", errors="replace"), True

    @staticmethod
    def _require_success(result: ExecResult, operation: str) -> None:
        if result.exit_code != 0:
            raise PiError(f"{operation} failed")