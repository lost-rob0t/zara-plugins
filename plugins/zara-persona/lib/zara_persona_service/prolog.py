"""Bounded SWI-Prolog execution for zara-persona."""

from __future__ import annotations

import subprocess
from pathlib import Path


class PersonaPrologError(RuntimeError):
    pass


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
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as error:
        raise PersonaPrologError(f"SWI-Prolog executable not found: {swipl_program}") from error
    except subprocess.TimeoutExpired as error:
        raise PersonaPrologError(
            f"persona Prolog query exceeded {timeout_seconds:.2f}s timeout"
        ) from error

    if len(completed.stdout) > output_limit or len(completed.stderr) > output_limit:
        raise PersonaPrologError("persona Prolog output exceeded configured limit")
    if completed.returncode != 0:
        error_text = completed.stderr.decode("utf-8", errors="replace").strip()
        error_text = " ".join(error_text.split())[:512]
        raise PersonaPrologError(
            f"persona Prolog query failed with exit {completed.returncode}: {error_text}"
        )

    try:
        return completed.stdout.decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise PersonaPrologError("persona Prolog output was not valid UTF-8") from error
