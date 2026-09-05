from __future__ import annotations

from collections.abc import Mapping


def build_repository_evidence(snapshot: Mapping[str, object]) -> dict[str, object]:
    root = snapshot.get("root")
    head = snapshot.get("head")
    branch = snapshot.get("branch")
    dirty = snapshot.get("dirty")
    if not isinstance(root, str) or not root:
        raise ValueError("repository snapshot root must be a non-empty string")
    if not isinstance(head, str) or len(head) not in (40, 64) or any(char not in "0123456789abcdefABCDEF" for char in head):
        raise ValueError("repository snapshot head must be a full Git object ID")
    if not isinstance(branch, str) or not branch:
        raise ValueError("repository snapshot branch must be a non-empty string")
    if not isinstance(dirty, bool):
        raise ValueError("repository snapshot dirty must be boolean")

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
        },
    }
