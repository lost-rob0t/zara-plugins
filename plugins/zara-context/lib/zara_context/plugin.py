from __future__ import annotations

import json

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .store import ContextError, ContextStore


PLUGIN_VERSION = "0.1.0"


class ZaraContextPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-context",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Short-lived structured active-context provider",
    )

    def __init__(self) -> None:
        self.store = ContextStore()

    def start(self, runtime) -> None:
        ttl = 30.0
        configuration = runtime.configuration
        if isinstance(configuration, dict):
            plugins = configuration.get("plugins")
            section = plugins.get("zara-context", {}) if isinstance(plugins, dict) else {}
            if isinstance(section, dict) and "default_ttl_seconds" in section:
                ttl = float(section["default_ttl_seconds"])
        self.store = ContextStore(default_ttl=ttl)

    def stop(self) -> None:
        return None

    def publish_context(self, category: str, value: object, *, source: str, confidence: float = 1.0, ttl: float | None = None):
        return self.store.update(category, value, source=source, confidence=confidence, ttl=ttl)

    def current(self, categories: str = "") -> str:
        requested = None
        if categories:
            values = [value.strip() for value in categories.split(",") if value.strip()]
            if len(values) > 16:
                raise ContextError("too many context categories requested")
            requested = values
        return json.dumps(self.store.current(requested), ensure_ascii=False, sort_keys=True)

    def tools(self):
        return (
            StructuredTool.from_function(
                func=self.current,
                name="context.current",
                description="Return bounded fresh and explicitly stale active context. Optional categories are comma-separated known context categories.",
            ),
        )


def create_plugin():
    return ZaraContextPlugin()
