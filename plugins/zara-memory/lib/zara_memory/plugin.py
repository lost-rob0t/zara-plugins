from __future__ import annotations

import json
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .domain import MemoryError, MemoryService
from .symbolic_memory_mcp import SUPPORTED_SCOPES as NATIVE_SCOPES
from .symbolic_memory_mcp import SymbolicMemoryMCP


PLUGIN_VERSION = "0.1.0"
APPROVAL_METADATA = {"zara_requires_approval": True}


class UnavailableMemoryBackend:
    def remember(self, **_: Any) -> dict[str, Any]:
        raise MemoryError("symbolic-memory-backend-not-configured")


class ZaraMemoryPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-memory",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Scoped symbolic-memory adapter with explicit persistence boundaries",
    )

    def __init__(self, backend: Any | None = None, native_client: Any | None = None) -> None:
        self.backend = backend or UnavailableMemoryBackend()
        self.memory = MemoryService(self.backend)
        self.native_client = native_client
        self.native_error = None if native_client is not None else "symbolic-memory-backend-not-configured"

    def start(self, runtime) -> None:
        if self.native_client is not None:
            return
        section = self._section(runtime.configuration)
        native = section.get("symbolic_memory")
        if native is None:
            self.native_error = "symbolic-memory-backend-not-configured"
            return
        if not isinstance(native, Mapping):
            raise ValueError("plugins.zara-memory.symbolic_memory must be a table")

        executable = self._required_string(native, "executable")
        database = Path(self._required_string(native, "database")).expanduser()
        if database == Path("/nix/store") or Path("/nix/store") in database.parents:
            raise ValueError("symbolic-memory mutable database must not live in the Nix store")
        principal = self._required_string(native, "principal")
        session_id = self._required_string(native, "session_id")
        capabilities = native.get("capabilities")
        if not isinstance(capabilities, (list, tuple)) or not capabilities or any(
            not isinstance(item, str) or not item for item in capabilities
        ):
            raise ValueError("symbolic_memory.capabilities must contain non-empty strings")
        project_remote = native.get("project_remote")
        if project_remote is not None and (not isinstance(project_remote, str) or not project_remote):
            raise ValueError("symbolic_memory.project_remote must be a non-empty string when configured")
        source_class = native.get("source_class", "model_inferred")
        if not isinstance(source_class, str) or not source_class:
            raise ValueError("symbolic_memory.source_class must be a non-empty string")

        resolved = executable if Path(executable).is_absolute() else shutil.which(executable)
        if resolved is None or (Path(executable).is_absolute() and not Path(executable).is_file()):
            self.native_error = "symbolic-memory-executable-not-found"
            return
        self.native_client = SymbolicMemoryMCP(
            executable=str(resolved),
            database=database,
            principal=principal,
            session_id=session_id,
            project_remote=project_remote,
            source_class=source_class,
            capabilities=tuple(capabilities),
        )
        self.native_error = None

    def stop(self) -> None:
        self.native_client = None
        self.native_error = "symbolic-memory-backend-not-configured"

    def status(self) -> str:
        configured = self.native_client is not None or not isinstance(self.backend, UnavailableMemoryBackend)
        backend_name = None
        if self.native_client is not None:
            backend_name = "symbolic-memory-mcp"
        elif not isinstance(self.backend, UnavailableMemoryBackend):
            backend_name = type(self.backend).__name__
        return json.dumps(
            {
                "configured": configured,
                "backend": backend_name,
                "supported_scopes": sorted(self.memory.supported_scopes),
                "native_supported_scopes": sorted(NATIVE_SCOPES),
                "error": None if configured else self.native_error,
            },
            sort_keys=True,
        )

    def remember(
        self,
        text: str,
        scope: str = "project",
        retention: str = "long_term",
        kind: str = "text",
    ) -> str:
        client = self._require_native()
        return json.dumps(
            client.remember(text, scope=scope, retention=retention, kind=kind),
            sort_keys=True,
        )

    def get(self, memory_id: str) -> str:
        client = self._require_native()
        return json.dumps(client.get(memory_id), sort_keys=True)

    def tools(self) -> Sequence[StructuredTool]:
        return (
            StructuredTool.from_function(
                func=self.status,
                name="memory.status",
                description="Report symbolic-memory backend availability and supported Zara/native scopes.",
            ),
            StructuredTool.from_function(
                func=self.remember,
                name="memory.remember",
                description=(
                    "Durably preserve exact source text in an authorized native symbolic-memory "
                    "session, project, or global namespace."
                ),
                metadata=APPROVAL_METADATA,
            ),
            StructuredTool.from_function(
                func=self.get,
                name="memory.get",
                description="Fetch one known native symbolic-memory record by stable ID when authorized.",
            ),
        )

    def _require_native(self):
        if self.native_client is None:
            raise RuntimeError(self.native_error or "symbolic-memory-backend-not-configured")
        return self.native_client

    @staticmethod
    def _section(configuration) -> Mapping[str, object]:
        if not isinstance(configuration, Mapping):
            return {}
        plugins = configuration.get("plugins", {})
        if not isinstance(plugins, Mapping):
            return {}
        section = plugins.get("zara-memory", {})
        if not isinstance(section, Mapping):
            raise ValueError("plugins.zara-memory must be a table")
        return section

    @staticmethod
    def _required_string(mapping: Mapping[str, object], key: str) -> str:
        value = mapping.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"symbolic_memory.{key} must be a non-empty string")
        return value


def create_plugin():
    return ZaraMemoryPlugin()
