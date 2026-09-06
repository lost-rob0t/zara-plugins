from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath


def build_repository_evidence(
    snapshot: Mapping[str, object],
    *,
    worktrees: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    if not isinstance(snapshot, Mapping):
        raise ValueError("repository snapshot must be structured")
    root = snapshot.get("root")
    head = snapshot.get("head")
    branch = snapshot.get("branch")
    dirty = snapshot.get("dirty")
    changed_paths = snapshot.get("changed_paths", ())
    if not isinstance(root, str) or not root:
        raise ValueError("repository snapshot root must be a non-empty string")
    if "\x00" in root:
        raise ValueError("repository snapshot root must not contain NUL")
    _require_canonical_absolute_path(root, "repository snapshot root")
    if not isinstance(head, str) or len(head) not in (40, 64) or any(char not in "0123456789abcdef" for char in head):
        raise ValueError("repository snapshot head must be a full Git object ID in canonical lowercase")
    if not isinstance(branch, str) or not branch:
        raise ValueError("repository snapshot branch must be a non-empty string")
    if any(character in branch for character in ("\x00", "\n", "\r")):
        raise ValueError("repository snapshot branch must be single-line text")
    if not isinstance(dirty, bool):
        raise ValueError("repository snapshot dirty must be boolean")
    if not isinstance(changed_paths, Sequence) or isinstance(changed_paths, (str, bytes)):
        raise ValueError("repository changed path evidence must be a bounded sequence")
    if len(changed_paths) > 100:
        raise ValueError("repository changed path evidence exceeds 100 entries")
    if any(not isinstance(path, str) or not path or "\x00" in path for path in changed_paths):
        raise ValueError("repository changed path evidence must be non-empty text without NUL")
    if any(PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts for path in changed_paths):
        raise ValueError("repository changed path evidence must stay repository-relative")
    if any(path == "." or str(PurePosixPath(path)) != path for path in changed_paths):
        raise ValueError("repository changed path evidence must use canonical repository-relative paths")
    if len(set(changed_paths)) != len(changed_paths):
        raise ValueError("repository changed path evidence contains duplicate changed paths")
    if dirty is not bool(changed_paths):
        raise ValueError("repository snapshot dirty state contradicts changed paths")
    if not isinstance(worktrees, Sequence) or isinstance(worktrees, (str, bytes)):
        raise ValueError("repository worktree evidence must be a bounded sequence")
    if len(worktrees) > 100:
        raise ValueError("repository worktree evidence exceeds 100 entries")
    if any(not isinstance(worktree, Mapping) for worktree in worktrees):
        raise ValueError("repository worktree evidence entry must be structured")

    worktree_values = [_worktree_lock_value(worktree) for worktree in worktrees]
    worktree_paths = [value["path"] for value in worktree_values]
    if len(set(worktree_paths)) != len(worktree_paths):
        raise ValueError("repository worktree evidence contains duplicate worktree paths")
    changed_path_values = [{"root": root, "path": path} for path in changed_paths]

    state_ref = {"root": root, "head": head}
    return {
        "source_class": "repository",
        "trust_class": "observed",
        "freshness": "current",
        "snapshot": dict(state_ref),
        "state_ref": dict(state_ref),
        "evidence_refs": [
            {
                "kind": "git_repository_snapshot",
                "root": root,
                "head": head,
            }
        ],
        "values": {
            "repository_head": {"root": root, "head": head},
            "repository_branch": {"root": root, "branch": branch},
            "repository_clean": {"root": root, "dirty": dirty},
            "repository_changed_path": changed_path_values,
            "worktree_locked": worktree_values,
        },
    }


def _worktree_lock_value(worktree: Mapping[str, object]) -> dict[str, object]:
    path = worktree.get("path")
    head = worktree.get("head")
    locked = worktree.get("locked")
    if not isinstance(path, str) or not path:
        raise ValueError("worktree evidence path must be a non-empty string")
    if "\x00" in path:
        raise ValueError("worktree evidence path must not contain NUL")
    _require_canonical_absolute_path(path, "worktree evidence path")
    if not isinstance(head, str) or len(head) not in (40, 64) or any(char not in "0123456789abcdef" for char in head):
        raise ValueError("worktree evidence head must be a full Git object ID in canonical lowercase")
    if locked is not None and not isinstance(locked, str):
        raise ValueError("worktree evidence lock state must be text or null")
    return {"path": path, "head": head, "locked": locked is not None}


def _require_canonical_absolute_path(value: str, label: str) -> None:
    path = PurePosixPath(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute")
    if str(path) != value or ".." in path.parts:
        raise ValueError(f"{label} must be canonical")
