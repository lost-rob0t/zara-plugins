"""Zara service plugin exposing Agent Zero delegation tools."""

from __future__ import annotations

import json

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .client import AgentZeroClient
from .config import AgentZeroConfig


PLUGIN_VERSION = "0.1.0"


class ZaraAgentZeroPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-agent-zero",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Delegate selected Zara work to Agent Zero",
    )

    def __init__(self) -> None:
        self._config = AgentZeroConfig()
        self._client = AgentZeroClient(self._config)

    def start(self, runtime) -> None:
        self._config = AgentZeroConfig.load(runtime.configuration)
        self._client = AgentZeroClient(self._config)

    def stop(self) -> None:
        return None

    def tools(self):
        return (
            StructuredTool.from_function(
                func=self.agent_zero_status,
                name="agent_zero_status",
                description="Return Agent Zero connector protocol, version, auth state, and capabilities.",
            ),
            StructuredTool.from_function(
                func=self.agent_zero_message,
                name="agent_zero_message",
                description=(
                    "Send one task or message to Agent Zero. Reuse context_id from a prior result "
                    "to continue the same Agent Zero conversation."
                ),
            ),
        )

    def agent_zero_status(self) -> str:
        return json.dumps(self._client.capabilities(), ensure_ascii=False, sort_keys=True)

    def agent_zero_message(
        self,
        message: str,
        context_id: str = "",
        project_name: str = "",
        agent_profile: str = "",
    ) -> str:
        result = self._client.send_message(
            message,
            context_id=context_id,
            project_name=project_name,
            agent_profile=agent_profile,
        )
        return json.dumps(result, ensure_ascii=False, sort_keys=True)


def create_plugin():
    return ZaraAgentZeroPlugin()
