from __future__ import annotations

import subprocess
from pathlib import Path

from .domain import CodingError, PrologRLMBridge


COMPILE_GOAL = (
    "read_string(user_input,_,S),"
    "zara_coding_assertions:registry(R),"
    "rlm_spec_lang:spec_source_compile(S,R,[series(zara_coding),version(1)],O),"
    "write_canonical(O),nl,halt"
)


def compile_spec(bridge: PrologRLMBridge, source: str) -> dict[str, str]:
    if not isinstance(source, str) or not source.strip():
        raise CodingError("SPEC source must be a non-empty string")
    if len(source) > bridge.MAX_SPEC_CHARS:
        raise CodingError(f"SPEC source exceeds {bridge.MAX_SPEC_CHARS} character limit")

    spec_language = bridge.checkout / "prolog" / "rlm_spec_lang.pl"
    provider = Path(__file__).resolve().parents[2] / "prolog" / "zara_coding_assertions.pl"
    if bridge._validate_checkout and not spec_language.is_file():
        raise CodingError("Prolog-RLM SPEC language module is unavailable")
    if not provider.is_file():
        raise CodingError("zara-coding trusted assertion registry is unavailable")

    argv = [
        bridge.executable,
        "-q",
        "-p",
        f"library={bridge.checkout / 'prolog'}",
        "-s",
        str(spec_language),
        "-s",
        str(provider),
        "-g",
        COMPILE_GOAL,
    ]
    try:
        result = bridge._runner(
            argv,
            input=source,
            check=True,
            capture_output=True,
            text=True,
            timeout=bridge.timeout_seconds,
            shell=False,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise CodingError("Prolog-RLM SPEC compilation failed") from exc

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise CodingError("Prolog-RLM SPEC compilation returned no outcome")
    outcome = lines[-1].strip()
    return {"status": "ok" if outcome.startswith("ok(") else "rejected", "outcome": outcome}
