from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping


class SSHError(RuntimeError):
    pass


@dataclass(frozen=True)
class HostPolicy:
    alias: str
    hostname: str
    username: str
    port: int
    remote_roots: tuple[str, ...]
    local_roots: tuple[Path, ...]
    max_transfer_bytes: int = 1024 * 1024 * 1024

    def __post_init__(self) -> None:
        for name, value, limit in (
            ("alias", self.alias, 64),
            ("hostname", self.hostname, 255),
            ("username", self.username, 128),
        ):
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise SSHError(f"{name} must be a canonical non-empty string")
            if len(value.encode("utf-8")) > limit or any(ord(c) < 0x20 for c in value):
                raise SSHError(f"{name} is invalid")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise SSHError("port is out of range")
        if type(self.max_transfer_bytes) is not int or self.max_transfer_bytes <= 0:
            raise SSHError("max_transfer_bytes must be a positive integer")
        if not self.remote_roots or not self.local_roots:
            raise SSHError("remote_roots and local_roots must be non-empty")
        for root in self.remote_roots:
            path = PurePosixPath(root)
            if not path.is_absolute() or ".." in path.parts:
                raise SSHError("remote root must be an absolute canonical POSIX path")
        for root in self.local_roots:
            path = Path(root).expanduser()
            if not path.is_absolute():
                raise SSHError("local root must be absolute")


class SSHDomain:
    def __init__(
        self,
        backend,
        policies: Mapping[str, HostPolicy],
        *,
        max_list_entries: int = 100,
    ) -> None:
        if type(max_list_entries) is not int or not 1 <= max_list_entries <= 1000:
            raise SSHError("max_list_entries is out of range")
        self.backend = backend
        self.policies = dict(policies)
        self.max_list_entries = max_list_entries
        if len(self.policies) > 64:
            raise SSHError("host policy limit exceeded")
        for alias, policy in self.policies.items():
            if alias != policy.alias:
                raise SSHError("host policy alias mismatch")

    def _policy(self, alias: str) -> HostPolicy:
        if not isinstance(alias, str) or alias not in self.policies:
            raise SSHError("unknown host alias")
        return self.policies[alias]

    @staticmethod
    def _remote(policy: HostPolicy, value: str) -> str:
        if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 4096:
            raise SSHError("remote_path is invalid")
        if any(ord(character) < 0x20 for character in value):
            raise SSHError("remote_path contains control characters")
        path = PurePosixPath(value)
        if not path.is_absolute() or ".." in path.parts:
            raise SSHError("remote_path must be an absolute canonical path")
        roots = tuple(PurePosixPath(root) for root in policy.remote_roots)
        if not any(path == root or root in path.parents for root in roots):
            raise SSHError("remote_path escapes configured roots")
        return str(path)

    @staticmethod
    def _local(policy: HostPolicy, value: str) -> Path:
        if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 4096:
            raise SSHError("local_path is invalid")
        if any(ord(character) < 0x20 for character in value):
            raise SSHError("local_path contains control characters")
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise SSHError("local_path must be absolute")
        resolved = path.resolve(strict=False)
        roots = tuple(Path(root).expanduser().resolve(strict=False) for root in policy.local_roots)
        if not any(resolved == root or root in resolved.parents for root in roots):
            raise SSHError("local_path escapes configured roots")
        if not resolved.parent.is_dir():
            raise SSHError("local destination parent does not exist")
        return resolved

    @staticmethod
    def _stat(value: object, remote_path: str) -> dict[str, object]:
        if not isinstance(value, dict):
            raise SSHError("SSH backend returned invalid stat")
        size = value.get("size")
        is_file = value.get("is_file")
        if type(size) is not int or size < 0:
            raise SSHError("SSH backend returned invalid size")
        if type(is_file) is not bool:
            raise SSHError("SSH backend returned invalid file type")
        return {"path": remote_path, "size": size, "is_file": is_file}

    def status(self) -> dict[str, object]:
        value = self.backend.status()
        if not isinstance(value, dict):
            raise SSHError("SSH backend returned invalid status")
        return {**value, "configured_host_count": len(self.policies)}

    def hosts(self) -> list[dict[str, object]]:
        values = []
        for alias in sorted(self.policies):
            policy = self.policies[alias]
            values.append(
                {
                    "alias": policy.alias,
                    "hostname": policy.hostname,
                    "username": policy.username,
                    "port": policy.port,
                    "remote_root_count": len(policy.remote_roots),
                    "local_root_count": len(policy.local_roots),
                    "max_transfer_bytes": policy.max_transfer_bytes,
                }
            )
        return values

    def file_stat(self, host_alias: str, remote_path: str) -> dict[str, object]:
        policy = self._policy(host_alias)
        remote = self._remote(policy, remote_path)
        return self._stat(self.backend.stat(host_alias, remote), remote)

    def file_list(
        self,
        host_alias: str,
        remote_path: str,
        *,
        limit: int = 50,
    ) -> dict[str, object]:
        policy = self._policy(host_alias)
        remote = self._remote(policy, remote_path)
        if type(limit) is not int or not 1 <= limit <= self.max_list_entries:
            raise SSHError("list limit is out of range")
        entries = self.backend.list_dir(host_alias, remote, limit)
        if not isinstance(entries, list):
            raise SSHError("SSH backend returned invalid directory listing")
        normalized = []
        for entry in entries[:limit]:
            if not isinstance(entry, dict):
                raise SSHError("SSH backend returned invalid directory entry")
            name = entry.get("name")
            size = entry.get("size")
            is_file = entry.get("is_file")
            if (
                not isinstance(name, str)
                or not name
                or "/" in name
                or "\\" in name
                or name in {".", ".."}
                or any(ord(character) < 0x20 for character in name)
            ):
                raise SSHError("SSH backend returned invalid entry name")
            if type(size) is not int or size < 0 or type(is_file) is not bool:
                raise SSHError("SSH backend returned invalid directory entry metadata")
            normalized.append({"name": name, "size": size, "is_file": is_file})
        return {"status": "ok", "host_alias": host_alias, "path": remote, "entries": normalized}

    def file_fetch(
        self,
        host_alias: str,
        remote_path: str,
        local_path: str,
    ) -> dict[str, object]:
        policy = self._policy(host_alias)
        remote = self._remote(policy, remote_path)
        local = self._local(policy, local_path)
        if local.exists():
            raise SSHError("local destination already exists")

        remote_stat = self._stat(self.backend.stat(host_alias, remote), remote)
        if not remote_stat["is_file"]:
            raise SSHError("remote_path is not a file")
        if remote_stat["size"] > policy.max_transfer_bytes:
            raise SSHError("remote file exceeds transfer limit")

        evidence = self.backend.fetch(host_alias, remote, local)
        if not isinstance(evidence, dict) or type(evidence.get("accepted")) is not bool:
            if local.exists():
                local.unlink()
            raise SSHError("SSH backend returned invalid fetch evidence")
        if evidence["accepted"] is not True:
            if local.exists():
                local.unlink()
            return {
                "status": "verification_failed",
                "accepted": False,
                "verified": False,
                "host_alias": host_alias,
                "remote_path": remote,
                "local_path": str(local),
            }

        if not local.is_file() or local.stat().st_size != remote_stat["size"]:
            if local.exists():
                local.unlink()
            return {
                "status": "verification_failed",
                "accepted": True,
                "verified": False,
                "host_alias": host_alias,
                "remote_path": remote,
                "local_path": str(local),
            }

        digest = hashlib.sha256()
        with local.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return {
            "status": "verified",
            "accepted": True,
            "verified": True,
            "host_alias": host_alias,
            "remote_path": remote,
            "local_path": str(local),
            "bytes": remote_stat["size"],
            "sha256": digest.hexdigest(),
        }
