"""Zara service plugin for sourced knowledge retrieval."""

from __future__ import annotations

import json

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .brave import BraveProvider, BraveProviderError
from .config import KnowledgeConfig
from .core import KnowledgeEngine


PLUGIN_VERSION = "0.1.0"


class ZaraKnowledgePlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-knowledge",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Provider-neutral sourced knowledge retrieval with a first-class Brave Search adapter",
    )

    def __init__(self) -> None:
        self._config = KnowledgeConfig()
        self._engine = KnowledgeEngine(())
        self._provider_error = "Brave Search is not configured"

    def start(self, runtime) -> None:
        self._config = KnowledgeConfig.load(runtime.configuration)
        if not self._config.brave_api_key:
            self._engine = KnowledgeEngine(())
            self._provider_error = "Brave Search is not configured"
            return
        provider = BraveProvider(
            api_key=self._config.brave_api_key,
            timeout_seconds=self._config.timeout_seconds,
            max_response_bytes=self._config.max_response_bytes,
        )
        self._engine = KnowledgeEngine((provider,))
        self._provider_error = ""

    def stop(self) -> None:
        return None

    def tools(self):
        return (
            StructuredTool.from_function(
                func=self.knowledge_search,
                name="knowledge.search",
                description="Search configured knowledge providers and return citation-ready sourced evidence with provenance.",
            ),
            StructuredTool.from_function(
                func=self.knowledge_status,
                name="knowledge.status",
                description="Report provider availability without exposing credentials.",
            ),
        )

    def knowledge_search(
        self,
        query: str,
        count: int = 5,
        language: str = "",
        safe_search: str = "moderate",
        freshness: str = "",
    ) -> str:
        if self._provider_error:
            return json.dumps(
                {
                    "query": query,
                    "results": [],
                    "errors": [
                        {
                            "provider": self._config.default_provider,
                            "kind": "unavailable",
                            "message": self._provider_error,
                        }
                    ],
                },
                sort_keys=True,
            )
        result = self._engine.search(
            query,
            count=min(count, self._config.max_results),
            language=language,
            safe_search=safe_search,
            freshness=freshness,
        )
        return json.dumps(result, ensure_ascii=False, sort_keys=True)

    def knowledge_status(self) -> str:
        return json.dumps(
            {
                "default_provider": self._config.default_provider,
                "providers": {
                    "brave": {
                        "configured": bool(self._config.brave_api_key),
                        "available": not bool(self._provider_error),
                    }
                },
            },
            sort_keys=True,
        )


def create_plugin():
    return ZaraKnowledgePlugin()
