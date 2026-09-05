from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .domain import MemoryError, MemoryService


PLUGIN_VERSION = "0.1.0"


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

    def __init__(self, backend: Any | None = None) -> None:
        self.backend = backend or UnavailableMemoryBackend()
        self.memory = MemoryService(self.backend)

    def start(self, runtime) -> None:
        return None

    def stop(self) -> None:
        return None

    def status(self) -> str:
        configured = not isinstance(self.backend, UnavailableMemoryBackend)
        return json.dumps(
            {
                "configured": configured,
                "backend": type(self.backend).__name__ if configured else None,
                "supported_scopes": sorted(self.memory.supported_scopes),
                "error": None if configured else "symbolic-memory-backend-not-configured",
            },
            sort_keys=True,
        )

    def tools(self):
        return (
            StructuredTool.from_function(
                func=self.status,
                name="memory.status",
                description="Report symbolic-memory backend availability and supported Zara memory scopes.",
            ),
        )


def create_plugin():
    return ZaraMemoryPlugin()
