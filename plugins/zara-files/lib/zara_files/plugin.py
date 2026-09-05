from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .files import FileDomain, FileDomainError


PLUGIN_VERSION = "0.1.0"


class ZaraFilesPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-files",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Root-confined structured local file operations",
    )

    def __init__(self) -> None:
        self.domain: FileDomain | None = None

    def start(self, runtime) -> None:
        configuration = runtime.configuration
        section = {}
        if isinstance(configuration, dict):
            plugins = configuration.get("plugins")
            if isinstance(plugins, dict):
                candidate = plugins.get("zara-files", {})
                if isinstance(candidate, dict):
                    section = candidate
        roots = section.get("roots", [])
        if roots is None:
            roots = []
        if not isinstance(roots, (list, tuple)):
            raise FileDomainError("zara-files roots must be a list")
        if not roots:
            self.domain = None
            return
        self.domain = FileDomain(
            [Path(str(value)).expanduser() for value in roots],
            max_read_bytes=int(section.get("max_read_bytes", 64 * 1024)),
            max_results=int(section.get("max_results", 64)),
        )

    def stop(self) -> None:
        self.domain = None

    def _require_domain(self) -> FileDomain:
        if self.domain is None:
            raise FileDomainError("file roots are not configured")
        return self.domain

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def status(self) -> str:
        if self.domain is None:
            return self._json({"status": "unavailable", "reason": "file-roots-not-configured"})
        return self._json({"status": "ready", "root_ids": sorted(self.domain._roots)})

    def search(self, name: str = "*") -> str:
        return self._json(self._require_domain().search(name=name))

    def metadata(self, root_id: str, relative_path: str) -> str:
        return self._json(self._require_domain().metadata(root_id, relative_path))

    def read_text(self, root_id: str, relative_path: str, max_bytes: int = 65536) -> str:
        return self._json(self._require_domain().read_text(root_id, relative_path, max_bytes=max_bytes))

    def create_text(self, root_id: str, relative_path: str, text: str) -> str:
        return self._json(self._require_domain().create_text(root_id, relative_path, text))

    def copy(self, source_root_id: str, source_path: str, destination_root_id: str, destination_path: str) -> str:
        return self._json(self._require_domain().copy(source_root_id, source_path, destination_root_id, destination_path))

    def move(self, source_root_id: str, source_path: str, destination_root_id: str, destination_path: str) -> str:
        return self._json(self._require_domain().move(source_root_id, source_path, destination_root_id, destination_path))

    def rename(self, root_id: str, relative_path: str, new_name: str) -> str:
        return self._json(self._require_domain().rename(root_id, relative_path, new_name))

    def delete(self, root_id: str, relative_path: str) -> str:
        return self._json(self._require_domain().delete(root_id, relative_path))

    def semantic_search(self, query: str) -> str:
        return self._json(self._require_domain().semantic_search(query))

    def tools(self):
        return (
            StructuredTool.from_function(func=self.status, name="files.status", description="Report configured root IDs without exposing host root paths."),
            StructuredTool.from_function(func=self.search, name="files.search", description="Search configured roots by bounded filename glob."),
            StructuredTool.from_function(func=self.metadata, name="files.metadata", description="Inspect metadata for a root-confined relative path."),
            StructuredTool.from_function(func=self.read_text, name="files.read_text", description="Read bounded UTF-8 text from a root-confined regular file."),
            StructuredTool.from_function(func=self.create_text, name="files.create_text", description="Create a new bounded text file without overwrite."),
            StructuredTool.from_function(func=self.copy, name="files.copy", description="Copy a regular file between configured roots without overwrite."),
            StructuredTool.from_function(func=self.move, name="files.move", description="Move a regular file between configured roots without overwrite."),
            StructuredTool.from_function(func=self.rename, name="files.rename", description="Rename a regular file to a single safe path component."),
            StructuredTool.from_function(func=self.delete, name="files.delete", description="Delete one explicit regular file and verify it is gone."),
            StructuredTool.from_function(func=self.semantic_search, name="files.semantic_search", description="Query an optional semantic index adapter; unavailable explicitly when none is configured."),
        )


def create_plugin():
    return ZaraFilesPlugin()
