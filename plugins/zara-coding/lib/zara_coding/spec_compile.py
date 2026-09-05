from __future__ import annotations

import subprocess
from pathlib import Path

from .domain import CodingError, PrologRLMBridge


CATALOG_GOAL = (
    "zara_coding_assertions:registry(R),"
    "rlm_spec_lang:spec_language_catalog(R,O),"
    "write_canonical(O),nl,halt"
)
COMPILE_GOAL = (
    "read_string(user_input,_,S),"
    "zara_coding_assertions:registry(R),"
    "rlm_spec_lang:spec_source_compile(S,R,[series(zara_coding),version(1)],O),"
    "write_canonical(O),nl,halt"
)


def catalog_spec(bridge: PrologRLMBridge) -> dict[str, str]:
    outcome = _run(bridge, CATALOG_GOAL, operation="catalog")
    return {"status": "ok" if outcome.startswith("ok(") else "rejected", "outcome": outcome}


def compile_spec(bridge: PrologRLMBridge, source: str) -> dict[str, str]:
    if not isinstance(source, str) or not source.strip():
        raise CodingError("SPEC source must be a non-empty string")
    if len(source) > bridge.MAX_SPEC_CHARS:
        raise CodingError(f"SPEC source exceeds {bridge.MAX_SPEC_CHARS} character limit")
    outcome = _run(bridge, COMPILE_GOAL, operation="compilation", input_text=source)
    return {"status": "ok" if outcome.startswith("ok(") else "rejected", "outcome": outcome}


def _run(
    bridge: PrologRLMBridge,
    goal: str,
    *,
    operation: str,
    input_text: str | None = None,
) -> str:
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
        goal,
    ]
    kwargs = {
        "check": True,
        "capture_output": True,
        "text": True,
        "timeout": bridge.timeout_seconds,
        "shell": False,
    }
    if input_text is not None:
        kwargs["input"] = input_text
    try:
        result = bridge._runner(argv, **kwargs)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise CodingError(f"Prolog-RLM SPEC {operation} failed") from exc

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise CodingError(f"Prolog-RLM SPEC {operation} returned no outcome")
    return lines[-1].strip()
