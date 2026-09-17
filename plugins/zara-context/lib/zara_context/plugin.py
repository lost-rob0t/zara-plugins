from __future__ import annotations

import json
from collections.abc import Mapping

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .store import ContextError, ContextStore
from .system import LinuxSystemContextProvider


PLUGIN_VERSION = "0.2.0"
MAX_HOOK_PRIORITY = 100_000


class ZaraContextPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-context",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Short-lived structured active context with provenance and freshness",
    )

    def __init__(self) -> None:
        self.store = ContextStore()
        self._system_context = LinuxSystemContextProvider()
        self._system_hook_registration_id = None

    def start(self, runtime) -> None:
        ttl = 30.0
        system_hook_enabled = False
        system_hook_priority = -1000
        configuration = runtime.configuration
        if isinstance(configuration, Mapping):
            plugins = configuration.get("plugins")
            section = plugins.get("zara-context", {}) if isinstance(plugins, Mapping) else {}
            if isinstance(section, Mapping):
                if "default_ttl_seconds" in section:
                    ttl = section["default_ttl_seconds"]
                if "system_context_hook_enabled" in section:
                    value = section["system_context_hook_enabled"]
                    if not isinstance(value, bool):
                        raise ValueError("system_context_hook_enabled must be boolean")
                    system_hook_enabled = value
                if "system_context_hook_priority" in section:
                    system_hook_priority = section["system_context_hook_priority"]

        if isinstance(system_hook_priority, bool) or not isinstance(system_hook_priority, int):
            raise ValueError("system_context_hook_priority must be an integer")
        if abs(system_hook_priority) > MAX_HOOK_PRIORITY:
            raise ValueError("system_context_hook_priority is outside the supported range")

        self.store = ContextStore(default_ttl=ttl)
        self._system_hook_registration_id = None
        if system_hook_enabled:
            self._system_hook_registration_id = runtime.register_agent_loop_advice(
                "before",
                system_hook_priority,
                self._inject_system_context,
            )

    def stop(self) -> None:
        return None

    def _inject_system_context(self, _llm_client, _tool_registry, state, **_kwargs) -> None:
        from zara.context import add_context_fragment

        add_context_fragment(
            state,
            self._system_context.render(),
            source="plugin:zara-context:linux-system",
        )

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

    def system_context(self) -> str:
        return self._system_context.render()

    def tools(self):
        return (
            StructuredTool.from_function(
                func=self.current,
                name="context.current",
                description="Return bounded fresh and explicitly stale active context. Optional categories are comma-separated known context categories.",
            ),
            StructuredTool.from_function(
                func=self.system_context,
                name="context.system",
                description="Return bounded non-secret Linux session facts such as kernel, architecture, desktop, and display session.",
            ),
        )


def create_plugin():
    return ZaraContextPlugin()
