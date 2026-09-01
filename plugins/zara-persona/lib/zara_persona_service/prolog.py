"""Bounded SWI-Prolog execution for zara-persona."""

from __future__ import annotations

import os
import selectors
import subprocess
import time
from pathlib import Path


class PersonaPrologError(RuntimeError):
    pass


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.kill()
    process.wait()


def load_prolog_context(
    *,
    swipl_program: str,
    prolog_file: Path,
    timeout_seconds: float,
    output_limit: int,
) -> str:
    goal = (
        "zara_persona:context(Context), "
        "string(Context), "
        "format('~s', [Context])"
    )
    command = [
        swipl_program,
        "-q",
        "-f",
        "none",
        "-s",
        str(prolog_file),
        "-g",
        goal,
        "-t",
        "halt",
    ]
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as error:
        raise PersonaPrologError(
            f"SWI-Prolog executable not found: {swipl_program}"
        ) from error

    stdout = bytearray()
    stderr = bytearray()
    streams = ((process.stdout, stdout), (process.stderr, stderr))
    selector = selectors.DefaultSelector()
    for stream, buffer in streams:
        if stream is not None:
            selector.register(stream, selectors.EVENT_READ, buffer)

    deadline = time.monotonic() + timeout_seconds
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _stop_process(process)
                raise PersonaPrologError(
                    f"persona Prolog query exceeded {timeout_seconds:.2f}s timeout"
                )
            for key, _ in selector.select(timeout=min(0.1, remaining)):
                chunk = os.read(key.fd, min(4096, output_limit + 1))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                buffer = key.data
                buffer.extend(chunk)
                if len(buffer) > output_limit:
                    _stop_process(process)
                    raise PersonaPrologError(
                        "persona Prolog output exceeded configured limit"
                    )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _stop_process(process)
            raise PersonaPrologError(
                f"persona Prolog query exceeded {timeout_seconds:.2f}s timeout"
            )
        try:
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as error:
            _stop_process(process)
            raise PersonaPrologError(
                f"persona Prolog query exceeded {timeout_seconds:.2f}s timeout"
            ) from error
    finally:
        selector.close()
        for stream, _ in streams:
            if stream is not None:
                stream.close()

    if returncode != 0:
        error_text = stderr.decode("utf-8", errors="replace").strip()
        error_text = " ".join(error_text.split())[:512]
        raise PersonaPrologError(
            f"persona Prolog query failed with exit {returncode}: {error_text}"
        )

    try:
        return stdout.decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise PersonaPrologError("persona Prolog output was not valid UTF-8") from error
