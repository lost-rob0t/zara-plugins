from __future__ import annotations

import fnmatch
import os
import shutil
import stat
from pathlib import Path


class FileDomainError(RuntimeError):
    pass


class FileDomain:
    def __init__(
        self,
        roots,
        *,
        max_read_bytes: int = 64 * 1024,
        max_results: int = 64,
        semantic_index=None,
    ) -> None:
        if not 1 <= int(max_read_bytes) <= 1024 * 1024:
            raise FileDomainError("max_read_bytes is out of range")
        if not 1 <= int(max_results) <= 512:
            raise FileDomainError("max_results is out of range")
        configured: dict[str, Path] = {}
        for index, raw_root in enumerate(roots):
            path = Path(raw_root).expanduser()
            try:
                info = path.lstat()
            except OSError as error:
                raise FileDomainError("configured root is unavailable") from error
            if stat.S_ISLNK(info.st_mode):
                raise FileDomainError("configured root must not be a symlink")
            if not stat.S_ISDIR(info.st_mode):
                raise FileDomainError("configured root must be a directory")
            configured[f"root-{index}"] = path.resolve(strict=True)
        if not configured:
            raise FileDomainError("at least one file root is required")
        self._roots = configured
        self.max_read_bytes = int(max_read_bytes)
        self.max_results = int(max_results)
        self.semantic_index = semantic_index

    @property
    def root_ids(self) -> tuple[str, ...]:
        return tuple(self._roots)

    def _root(self, root_id: str) -> Path:
        if root_id not in self._roots:
            raise FileDomainError("unknown root")
        return self._roots[root_id]

    @staticmethod
    def _parts(relative_path: str) -> tuple[str, ...]:
        if not isinstance(relative_path, str) or not relative_path:
            raise FileDomainError("relative path is required")
        if len(relative_path.encode("utf-8")) > 4096:
            raise FileDomainError("relative path exceeds byte limit")
        path = Path(relative_path)
        if path.is_absolute():
            raise FileDomainError("absolute paths are not allowed")
        parts = path.parts
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise FileDomainError("path traversal is not allowed")
        return parts

    def _checked_path(
        self,
        root_id: str,
        relative_path: str,
        *,
        require_exists: bool = True,
        allow_leaf_symlink: bool = False,
    ) -> Path:
        root = self._root(root_id)
        parts = self._parts(relative_path)
        current = root
        for index, part in enumerate(parts):
            current = current / part
            last = index == len(parts) - 1
            try:
                info = current.lstat()
            except FileNotFoundError:
                if last and not require_exists:
                    return current
                raise FileDomainError("file path does not exist")
            except OSError as error:
                raise FileDomainError("file path cannot be inspected") from error
            if stat.S_ISLNK(info.st_mode) and (not last or not allow_leaf_symlink):
                raise FileDomainError("symlink paths are not allowed")
        return current

    def _destination(self, root_id: str, relative_path: str) -> Path:
        root = self._root(root_id)
        parts = self._parts(relative_path)
        parent = root
        for part in parts[:-1]:
            parent = parent / part
            try:
                info = parent.lstat()
            except OSError as error:
                raise FileDomainError("destination parent does not exist") from error
            if stat.S_ISLNK(info.st_mode):
                raise FileDomainError("symlink destination parents are not allowed")
            if not stat.S_ISDIR(info.st_mode):
                raise FileDomainError("destination parent is not a directory")
        destination = parent / parts[-1]
        if os.path.lexists(destination):
            raise FileDomainError("destination already exists")
        return destination

    @staticmethod
    def _kind(info: os.stat_result) -> str:
        if stat.S_ISREG(info.st_mode):
            return "file"
        if stat.S_ISDIR(info.st_mode):
            return "directory"
        return "other"

    def _render_metadata(self, root_id: str, relative_path: str, path: Path) -> dict[str, object]:
        info = path.lstat()
        return {
            "root_id": root_id,
            "relative_path": relative_path,
            "kind": self._kind(info),
            "size": info.st_size,
            "mtime_ns": info.st_mtime_ns,
        }

    def metadata(self, root_id: str, relative_path: str) -> dict[str, object]:
        path = self._checked_path(root_id, relative_path)
        return self._render_metadata(root_id, relative_path, path)

    def search(self, *, name: str = "*") -> list[dict[str, object]]:
        if not isinstance(name, str) or not name or len(name.encode("utf-8")) > 256:
            raise FileDomainError("search name pattern is invalid")
        results: list[dict[str, object]] = []
        for root_id, root in self._roots.items():
            for directory, directories, files in os.walk(root, followlinks=False):
                directory_path = Path(directory)
                safe_directories: list[str] = []
                for child in directories:
                    child_path = directory_path / child
                    try:
                        if stat.S_ISLNK(child_path.lstat().st_mode):
                            continue
                    except OSError:
                        continue
                    safe_directories.append(child)
                directories[:] = safe_directories
                for child in sorted(files):
                    if not fnmatch.fnmatch(child, name):
                        continue
                    candidate = directory_path / child
                    try:
                        info = candidate.lstat()
                    except OSError:
                        continue
                    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                        continue
                    relative = candidate.relative_to(root).as_posix()
                    results.append(self._render_metadata(root_id, relative, candidate))
                    if len(results) >= self.max_results:
                        return results
        return results

    def read_text(
        self,
        root_id: str,
        relative_path: str,
        *,
        max_bytes: int | None = None,
    ) -> dict[str, object]:
        path = self._checked_path(root_id, relative_path)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise FileDomainError("text read requires a regular file")
        limit = self.max_read_bytes if max_bytes is None else int(max_bytes)
        if not 1 <= limit <= self.max_read_bytes:
            raise FileDomainError("read byte limit is out of range")
        try:
            with path.open("rb") as stream:
                payload = stream.read(limit + 1)
        except OSError as error:
            raise FileDomainError("file could not be read") from error
        if b"\x00" in payload:
            raise FileDomainError("binary file is metadata-only")
        truncated = len(payload) > limit
        payload = payload[:limit]
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise FileDomainError("binary or non-UTF-8 file is metadata-only") from error
        return {
            "root_id": root_id,
            "relative_path": relative_path,
            "text": text,
            "truncated": truncated,
            "bytes": len(payload),
        }

    def create_text(self, root_id: str, relative_path: str, text: str) -> dict[str, object]:
        if not isinstance(text, str):
            raise FileDomainError("file content must be text")
        payload = text.encode("utf-8")
        if len(payload) > self.max_read_bytes:
            raise FileDomainError("file content exceeds byte limit")
        destination = self._destination(root_id, relative_path)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(destination, flags, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as error:
            raise FileDomainError("file could not be created safely") from error
        return self.metadata(root_id, relative_path)

    def copy(
        self,
        source_root_id: str,
        source_path: str,
        destination_root_id: str,
        destination_path: str,
    ) -> dict[str, object]:
        source = self._checked_path(source_root_id, source_path)
        if not stat.S_ISREG(source.lstat().st_mode):
            raise FileDomainError("copy source must be a regular file")
        destination = self._destination(destination_root_id, destination_path)
        try:
            with source.open("rb") as source_stream:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
                flags |= getattr(os, "O_NOFOLLOW", 0)
                fd = os.open(destination, flags, 0o600)
                with os.fdopen(fd, "wb") as destination_stream:
                    shutil.copyfileobj(source_stream, destination_stream, length=64 * 1024)
                    destination_stream.flush()
                    os.fsync(destination_stream.fileno())
        except OSError as error:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
            raise FileDomainError("file copy failed") from error
        return self.metadata(destination_root_id, destination_path)

    def move(
        self,
        source_root_id: str,
        source_path: str,
        destination_root_id: str,
        destination_path: str,
    ) -> dict[str, object]:
        source = self._checked_path(source_root_id, source_path)
        if not stat.S_ISREG(source.lstat().st_mode):
            raise FileDomainError("move source must be a regular file")
        destination = self._destination(destination_root_id, destination_path)
        try:
            if source_root_id == destination_root_id:
                os.rename(source, destination)
            else:
                self.copy(source_root_id, source_path, destination_root_id, destination_path)
                source.unlink()
        except FileDomainError:
            raise
        except OSError as error:
            raise FileDomainError("file move failed") from error
        return self.metadata(destination_root_id, destination_path)

    def rename(self, root_id: str, relative_path: str, new_name: str) -> dict[str, object]:
        if not isinstance(new_name, str) or not new_name or Path(new_name).name != new_name:
            raise FileDomainError("new name must be one path component")
        if new_name in {".", ".."} or len(new_name.encode("utf-8")) > 255:
            raise FileDomainError("new name is invalid")
        source_parts = self._parts(relative_path)
        destination = "/".join((*source_parts[:-1], new_name))
        return self.move(root_id, relative_path, root_id, destination)

    def delete(self, root_id: str, relative_path: str) -> dict[str, object]:
        path = self._checked_path(root_id, relative_path)
        if stat.S_ISDIR(path.lstat().st_mode):
            raise FileDomainError("directory deletion is not supported")
        if not stat.S_ISREG(path.lstat().st_mode):
            raise FileDomainError("delete target must be a regular file")
        try:
            path.unlink()
        except OSError as error:
            raise FileDomainError("file delete failed") from error
        if os.path.lexists(path):
            raise FileDomainError("file delete could not be verified")
        return {"deleted": True, "root_id": root_id, "relative_path": relative_path}

    def semantic_search(self, query: str) -> dict[str, object]:
        if not isinstance(query, str) or not query.strip() or len(query.encode("utf-8")) > 4096:
            raise FileDomainError("semantic query is invalid")
        if self.semantic_index is None:
            return {"status": "unavailable", "reason": "semantic-index-not-configured", "results": []}
        results = self.semantic_index.search(query, limit=self.max_results)
        if not isinstance(results, list):
            raise FileDomainError("semantic index returned invalid results")
        return {"status": "ok", "results": results[: self.max_results]}
