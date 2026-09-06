from __future__ import annotations

import math
import os
import selectors
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence


class ShellError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandPolicy:
    allowed_programs: set[str]
    allowed_roots: tuple[Path, ...]
    allowed_environment: set[str] = field(default_factory=set)
    max_runtime_seconds: float = 10.0
    max_output_bytes: int = 65536
    max_input_bytes: int = 65536
    max_environment_bytes: int = 4096

    def __post_init__(self) -> None:
        if not self.allowed_programs:
            raise ValueError("allowed_programs must not be empty")
        if not self.allowed_roots:
            raise ValueError("allowed_roots must not be empty")
        if any(not isinstance(name, str) or not name for name in self.allowed_environment):
            raise ValueError("allowed_environment must contain non-empty strings")
        if not math.isfinite(self.max_runtime_seconds) or self.max_runtime_seconds <= 0:
            raise ValueError("max_runtime_seconds must be finite positive")
        byte_limits = (self.max_output_bytes, self.max_input_bytes, self.max_environment_bytes)
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in byte_limits):
            raise ValueError("byte limits must be positive integers")


class ShellRunner:
    def __init__(self, policy: CommandPolicy) -> None:
        self.policy = policy
        self._roots = tuple(Path(root).resolve() for root in policy.allowed_roots)

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str] | None = None,
        stdin: str = "",
    ) -> dict[str, object]:
        command = self._validate_argv(argv)
        working_directory = self._validate_cwd(cwd)
        if env is None:
            environment = self._validate_env({})
        elif not isinstance(env, Mapping):
            raise ShellError("environment must be a mapping")
        else:
            environment = self._validate_env(env)
        if not isinstance(stdin, str):
            raise ShellError("stdin must be text")
        stdin_bytes = stdin.encode("utf-8")
        if len(stdin_bytes) > self.policy.max_input_bytes:
            raise ShellError("input exceeds configured limit")

        process = subprocess.Popen(
            command,
            cwd=working_directory,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            start_new_session=True,
        )
        if process.stdin is not None:
            try:
                process.stdin.write(stdin_bytes)
                process.stdin.close()
            except BrokenPipeError:
                pass

        stdout, stderr, stdout_truncated, stderr_truncated, timed_out = self._collect(process)
        exit_code = None if timed_out else process.returncode
        return {
            "argv": list(argv),
            "cwd": str(working_directory),
            "exit_code": exit_code,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "timed_out": timed_out,
        }

    def _validate_argv(self, argv: Sequence[str]) -> list[str]:
        if not argv or not all(isinstance(item, str) and item for item in argv):
            raise ShellError("argv must contain non-empty strings")
        requested = argv[0]
        if requested not in self.policy.allowed_programs:
            raise ShellError(f"program is not allowed: {requested}")
        if os.path.sep in requested:
            resolved = Path(requested)
            if not resolved.is_absolute():
                raise ShellError("allowed program path must be absolute")
            executable = str(resolved)
        else:
            found = shutil.which(requested)
            if found is None:
                raise ShellError(f"allowed program is unavailable: {requested}")
            executable = found
        return [executable, *argv[1:]]

    def _validate_cwd(self, cwd: Path) -> Path:
        resolved = Path(cwd).resolve()
        if not resolved.is_dir():
            raise ShellError("cwd must be an existing directory")
        if not any(resolved == root or root in resolved.parents for root in self._roots):
            raise ShellError("cwd is outside allowed roots")
        return resolved

    def _validate_env(self, env: Mapping[str, str]) -> dict[str, str]:
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in env.items()):
            raise ShellError("environment must contain string keys and values")
        for key in env:
            if key not in self.policy.allowed_environment:
                raise ShellError(f"environment variable is not allowed: {key}")
        size = sum(len(key.encode("utf-8")) + len(value.encode("utf-8")) + 2 for key, value in env.items())
        if size > self.policy.max_environment_bytes:
            raise ShellError("environment exceeds configured limit")
        return dict(env)

    def _collect(self, process: subprocess.Popen) -> tuple[bytes, bytes, bool, bool, bool]:
        stdout = bytearray()
        stderr = bytearray()
        stdout_truncated = False
        stderr_truncated = False
        selector = selectors.DefaultSelector()
        streams = ((process.stdout, stdout, "stdout"), (process.stderr, stderr, "stderr"))
        for stream, buffer, label in streams:
            if stream is not None:
                selector.register(stream, selectors.EVENT_READ, (buffer, label))

        deadline = time.monotonic() + self.policy.max_runtime_seconds
        timed_out = False
        try:
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    self._kill(process)
                    break
                for key, _ in selector.select(timeout=min(0.05, remaining)):
                    chunk = os.read(key.fd, 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    buffer, label = key.data
                    available = max(0, self.policy.max_output_bytes - len(buffer))
                    if available:
                        buffer.extend(chunk[:available])
                    if len(chunk) > available:
                        if label == "stdout":
                            stdout_truncated = True
                        else:
                            stderr_truncated = True
            if not timed_out:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    self._kill(process)
                else:
                    try:
                        process.wait(timeout=remaining)
                    except subprocess.TimeoutExpired:
                        timed_out = True
                        self._kill(process)
        finally:
            selector.close()
            for stream, _, _ in streams:
                if stream is not None:
                    stream.close()
        return bytes(stdout), bytes(stderr), stdout_truncated, stderr_truncated, timed_out

    @staticmethod
    def _kill(process: subprocess.Popen) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
