from __future__ import annotations

from pathlib import Path

from .domain import CodingError, RepositoryInspector

MAX_LOCK_REASON_CHARS = 256


def add_detached_worktree(
    inspector: RepositoryInspector,
    repository: Path,
    target: Path,
    expected_head: str,
) -> dict[str, object]:
    inspector._require_full_object_id(expected_head)
    root = inspector._repository_root(repository)
    target_path = Path(target).expanduser().resolve()
    inspector._require_allowed(target_path)
    if target_path.exists() or target_path.is_symlink():
        raise CodingError("worktree target already exists")
    if not target_path.parent.is_dir():
        raise CodingError("worktree target parent must be an existing directory")

    try:
        resolved = inspector._git(root, "rev-parse", "--verify", f"{expected_head}^{{commit}}").strip()
    except CodingError as exc:
        raise CodingError("expected_head is not a commit in this repository") from exc
    if resolved.lower() != expected_head.lower():
        raise CodingError("expected_head must identify the commit object directly")

    inspector._git(root, "worktree", "add", "--detach", str(target_path), expected_head)
    return {"path": str(target_path), "head": expected_head, "detached": True}


def add_detached_locked_worktree(
    inspector: RepositoryInspector,
    repository: Path,
    target: Path,
    expected_head: str,
    reason: str,
) -> dict[str, object]:
    reason = _require_lock_reason(reason)
    created = add_detached_worktree(inspector, repository, target, expected_head)
    locked = lock_worktree(inspector, repository, target, expected_head, reason)
    if locked["path"] != created["path"] or locked["head"] != created["head"]:
        raise CodingError("worktree identity changed during add-and-lock transaction")
    return locked


def lock_worktree(
    inspector: RepositoryInspector,
    repository: Path,
    target: Path,
    expected_head: str,
    reason: str,
) -> dict[str, object]:
    inspector._require_full_object_id(expected_head)
    reason = _require_lock_reason(reason)
    root = inspector._repository_root(repository)
    target_path = _resolve_target(inspector, target)
    record = _find_worktree(inspector, root, target_path)
    _require_lockable_detached(root, record, expected_head)
    if record["locked"] is not None:
        raise CodingError("worktree is already locked")

    inspector._git(root, "worktree", "lock", "--reason", reason, str(target_path))
    return {
        "path": str(target_path),
        "head": expected_head,
        "detached": True,
        "locked": reason,
    }


def unlock_worktree(
    inspector: RepositoryInspector,
    repository: Path,
    target: Path,
    expected_head: str,
    reason: str,
) -> dict[str, object]:
    inspector._require_full_object_id(expected_head)
    reason = _require_lock_reason(reason)
    root = inspector._repository_root(repository)
    target_path = _resolve_target(inspector, target)
    record = _find_worktree(inspector, root, target_path)
    _require_lockable_detached(root, record, expected_head)
    if record["locked"] is None:
        raise CodingError("worktree is not locked")
    if record["locked"] != reason:
        raise CodingError("worktree lock coordination reason changed")

    inspector._git(root, "worktree", "unlock", str(target_path))
    return {
        "path": str(target_path),
        "head": expected_head,
        "detached": True,
        "locked": None,
    }


def _require_lock_reason(reason: str) -> str:
    if not isinstance(reason, str) or not reason or len(reason) > MAX_LOCK_REASON_CHARS:
        raise ValueError(f"reason must be a non-empty string of at most {MAX_LOCK_REASON_CHARS} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in reason):
        raise ValueError("reason must not contain control characters")
    return reason


def _resolve_target(inspector: RepositoryInspector, target: Path) -> Path:
    target_path = Path(target).expanduser().resolve()
    inspector._require_allowed(target_path)
    return target_path


def _find_worktree(
    inspector: RepositoryInspector,
    root: Path,
    target: Path,
) -> dict[str, object]:
    for record in inspector.worktrees(root, limit=100):
        if record["path"] == str(target):
            return record
    raise CodingError("worktree target is not registered")


def _require_lockable_detached(
    root: Path,
    record: dict[str, object],
    expected_head: str,
) -> None:
    if record["path"] == str(root.resolve()):
        raise CodingError("primary worktree cannot be coordination-locked")
    if record["detached"] is not True or record["branch"] is not None:
        raise CodingError("worktree coordination locking requires a detached worktree")
    if not isinstance(record["head"], str) or record["head"].lower() != expected_head.lower():
        raise CodingError("worktree HEAD changed since expected_head was observed")
    if record["prunable"] is not None:
        raise CodingError("prunable worktree cannot be coordination-locked")
