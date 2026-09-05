from __future__ import annotations

from pathlib import Path

from .domain import CodingError, RepositoryInspector


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
