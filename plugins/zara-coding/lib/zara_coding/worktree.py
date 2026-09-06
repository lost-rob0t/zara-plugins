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
    try:
        try:
            record = _find_worktree(inspector, root, target_path)
        except CodingError as exc:
            raise CodingError("created worktree was not registered") from exc
        if (
            record["detached"] is not True
            or record["branch"] is not None
            or not isinstance(record["head"], str)
            or record["head"].lower() != expected_head.lower()
        ):
            raise CodingError("created worktree identity changed after creation")
    except CodingError as proof_error:
        try:
            _rollback_created_worktree(inspector, repository, target, expected_head)
        except CodingError as rollback_error:
            raise CodingError(f"{proof_error}; rollback could not safely remove created worktree") from rollback_error
        raise CodingError(f"{proof_error}; created worktree rolled back") from proof_error
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
    try:
        locked = lock_worktree(inspector, repository, target, expected_head, reason)
    except (CodingError, ValueError) as exc:
        try:
            _rollback_created_worktree(inspector, repository, target, expected_head)
        except CodingError as rollback_error:
            raise CodingError(
                "worktree lock failed and rollback could not safely remove created worktree"
            ) from rollback_error
        raise CodingError("worktree lock failed; created worktree rolled back") from exc
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
    try:
        locked_record = _find_worktree(inspector, root, target_path)
    except CodingError as exc:
        raise CodingError("worktree lock state was not established") from exc
    if (
        locked_record["detached"] is not True
        or locked_record["branch"] is not None
        or not isinstance(locked_record["head"], str)
        or locked_record["head"].lower() != expected_head.lower()
        or locked_record["prunable"] is not None
    ):
        raise CodingError("worktree identity changed after lock")
    if locked_record["locked"] != reason:
        raise CodingError("worktree lock state was not established")
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


def remove_detached_worktree(
    inspector: RepositoryInspector,
    repository: Path,
    target: Path,
    expected_head: str,
) -> dict[str, object]:
    inspector._require_full_object_id(expected_head)
    root = inspector._repository_root(repository)
    target_path = _resolve_target(inspector, target)
    record = _find_worktree(inspector, root, target_path)
    _require_lockable_detached(root, record, expected_head)
    if record["locked"] is not None:
        raise CodingError("worktree is locked; unlock it with the matching coordination reason before removal")
    _remove_worktree_and_prove_absent(inspector, root, target_path)
    return {"path": str(target_path), "head": expected_head, "removed": True}


def _rollback_created_worktree(
    inspector: RepositoryInspector,
    repository: Path,
    target: Path,
    expected_head: str,
) -> None:
    root = inspector._repository_root(repository)
    target_path = _resolve_target(inspector, target)
    record = _find_worktree(inspector, root, target_path)
    _require_lockable_detached(root, record, expected_head)
    if record["locked"] is not None:
        raise CodingError("created worktree became locked before rollback")
    _remove_worktree_and_prove_absent(inspector, root, target_path, context="created worktree")


def _remove_worktree_and_prove_absent(
    inspector: RepositoryInspector,
    root: Path,
    target_path: Path,
    *,
    context: str = "worktree",
) -> None:
    inspector._git(root, "worktree", "remove", str(target_path))
    for remaining in inspector.worktrees(root, limit=100):
        if remaining["path"] == str(target_path):
            raise CodingError(f"{context} remained registered after removal")
    if target_path.exists() or target_path.is_symlink():
        raise CodingError(f"{context} path remained after removal")


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
