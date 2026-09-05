from __future__ import annotations

from collections.abc import Mapping, Sequence


def build_repository_evidence(
    snapshot: Mapping[str, object],
    *,
    worktrees: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    root = snapshot.get("root")
    head = snapshot.get("head")
    branch = snapshot.get("branch")
    dirty = snapshot.get("dirty")
    changed_paths = snapshot.get("changed_paths", ())
    if not isinstance(root, str) or not root:
        raise ValueError("repository snapshot root must be a non-empty string")
    if not isinstance(head, str) or len(head) not in (40, 64) or any(char not in "0123456789abcdefABCDEF" for char in head):
        raise ValueError("repository snapshot head must be a full Git object ID")
    if not isinstance(branch, str) or not branch:
        raise ValueError("repository snapshot branch must be a non-empty string")
    if not isinstance(dirty, bool):
        raise ValueError("repository snapshot dirty must be boolean")
    if not isinstance(changed_paths, Sequence) or isinstance(changed_paths, (str, bytes)):
        raise ValueError("repository changed path evidence must be a bounded sequence")
    if len(changed_paths) > 100:
        raise ValueError("repository changed path evidence exceeds 100 entries")
    if any(not isinstance(path, str) or not path or "\x00" in path for path in changed_paths):
        raise ValueError("repository changed path evidence must be non-empty text without NUL")

    worktree_values = [_worktree_lock_value(worktree) for worktree in worktrees]
    if len(worktree_values) > 100:
        raise ValueError("repository worktree evidence exceeds 100 entries")
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
    if not isinstance(head, str) or len(head) not in (40, 64) or any(char not in "0123456789abcdefABCDEF" for char in head):
        raise ValueError("worktree evidence head must be a full Git object ID")
    if locked is not None and not isinstance(locked, str):
        raise ValueError("worktree evidence lock state must be text or null")
    return {"path": path, "head": head, "locked": locked is not None}
