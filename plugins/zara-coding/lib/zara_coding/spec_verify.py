from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from .domain import CodingError, PrologRLMBridge


MAX_FROZEN_SPEC_CHARS = 262_144
VERIFY_GOAL = (
    "read_term(user_input,F,[syntax_errors(error)]),"
    "zara_coding_verify:json_read_dict(user_input,E),"
    "zara_coding_verify:verify_repository(F,E,O),"
    "write_canonical(O),nl,halt"
)


def verify_repository_spec(
    bridge: PrologRLMBridge,
    frozen_outcome: str,
    evidence: Mapping[str, object],
) -> dict[str, str]:
    frozen = _frozen_outcome(frozen_outcome)
    payload = _repository_payload(evidence)

    verify_module = bridge.checkout / "prolog" / "rlm_verify.pl"
    plugin_root = Path(__file__).resolve().parents[2]
    provider = plugin_root / "prolog" / "zara_coding_assertions.pl"
    adapter = plugin_root / "prolog" / "zara_coding_verify.pl"
    if bridge._validate_checkout and not verify_module.is_file():
        raise CodingError("Prolog-RLM verification module is unavailable")
    if not provider.is_file() or not adapter.is_file():
        raise CodingError("zara-coding verification bridge is unavailable")

    argv = [
        bridge.executable,
        "-q",
        "-s",
        str(verify_module),
        "-s",
        str(provider),
        "-s",
        str(adapter),
        "-g",
        VERIFY_GOAL,
    ]
    input_text = f"{frozen}.\n{json.dumps(payload, separators=(',', ':'))}\n"
    try:
        result = bridge._runner(
            argv,
            check=True,
            capture_output=True,
            text=True,
            timeout=bridge.timeout_seconds,
            shell=False,
            input=input_text,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise CodingError("Prolog-RLM SPEC verification failed") from exc

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise CodingError("Prolog-RLM SPEC verification returned no outcome")
    outcome = lines[-1].strip()
    return {"status": "ok" if outcome.startswith("ok(") else "rejected", "outcome": outcome}


def _frozen_outcome(value: str) -> str:
    if not isinstance(value, str):
        raise CodingError("frozen SPEC outcome must be a string")
    frozen = value.strip()
    if not frozen.startswith("ok(frozen_spec{") or not frozen.endswith(")"):
        raise CodingError("frozen SPEC outcome must be canonical successful compiler output")
    if "\n" in frozen or "\r" in frozen or len(frozen) > MAX_FROZEN_SPEC_CHARS:
        raise CodingError("frozen SPEC outcome is not bounded canonical data")
    return frozen


def _repository_payload(evidence: Mapping[str, object]) -> dict[str, object]:
    if (
        evidence.get("source_class") != "repository"
        or evidence.get("trust_class") != "observed"
        or evidence.get("freshness") != "current"
    ):
        raise CodingError("repository evidence must be current observed repository evidence")

    snapshot = evidence.get("snapshot")
    values = evidence.get("values")
    if not isinstance(snapshot, Mapping) or not isinstance(values, Mapping):
        raise CodingError("repository evidence is missing snapshot values")
    head_value = values.get("repository_head")
    branch_value = values.get("repository_branch")
    clean_value = values.get("repository_clean")
    changed_path_values = values.get("repository_changed_path", [])
    worktree_values = values.get("worktree_locked", [])
    if not all(isinstance(value, Mapping) for value in (head_value, branch_value, clean_value)):
        raise CodingError("repository evidence is missing trusted assertion values")
    if not isinstance(changed_path_values, Sequence) or isinstance(changed_path_values, (str, bytes)):
        raise CodingError("repository evidence changed paths must be a bounded sequence")
    if len(changed_path_values) > 100:
        raise CodingError("repository evidence changed paths exceed 100 entries")
    if not isinstance(worktree_values, Sequence) or isinstance(worktree_values, (str, bytes)):
        raise CodingError("repository evidence worktree state must be a bounded sequence")
    if len(worktree_values) > 100:
        raise CodingError("repository evidence worktree state exceeds 100 entries")

    root = snapshot.get("root")
    head = snapshot.get("head")
    branch = branch_value.get("branch")
    dirty = clean_value.get("dirty")
    if head_value.get("root") != root or head_value.get("head") != head:
        raise CodingError("repository evidence head does not match snapshot")
    if branch_value.get("root") != root:
        raise CodingError("repository evidence branch does not match snapshot")
    if clean_value.get("root") != root:
        raise CodingError("repository evidence dirty state does not match snapshot")
    if (
        not isinstance(root, str)
        or not root
        or not isinstance(head, str)
        or not isinstance(branch, str)
        or not branch
        or not isinstance(dirty, bool)
    ):
        raise CodingError("repository evidence contains invalid snapshot values")

    changed_paths = [_changed_path_payload(value, root) for value in changed_path_values]
    worktrees = [_worktree_payload(value) for value in worktree_values]
    return {
        "root": root,
        "head": head,
        "branch": branch,
        "dirty": dirty,
        "changed_paths": changed_paths,
        "worktrees": worktrees,
    }


def _changed_path_payload(value: object, root: str) -> str:
    if not isinstance(value, Mapping):
        raise CodingError("repository evidence changed path entry must be structured")
    if value.get("root") != root:
        raise CodingError("repository evidence changed path does not match snapshot")
    path = value.get("path")
    if not isinstance(path, str) or not path or "\x00" in path:
        raise CodingError("repository evidence changed path must be non-empty text without NUL")
    return path


def _worktree_payload(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise CodingError("repository evidence worktree entry must be structured")
    path = value.get("path")
    head = value.get("head")
    locked = value.get("locked")
    if not isinstance(path, str) or not path:
        raise CodingError("repository evidence worktree path must be non-empty")
    if (
        not isinstance(head, str)
        or len(head) not in (40, 64)
        or any(char not in "0123456789abcdefABCDEF" for char in head)
    ):
        raise CodingError("repository evidence worktree head must be a full Git object ID")
    if not isinstance(locked, bool):
        raise CodingError("repository evidence worktree locked state must be boolean")
    return {"path": path, "head": head, "locked": locked}
