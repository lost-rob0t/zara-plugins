"""Optional native-Prolog policy tools and plugin-owned conversation advice."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.messages import SystemMessage
from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .advice import prepare_messages, previous_output, remove_advice
from .client import PolicyClient

logger = logging.getLogger(__name__)


class PolicyPlugin(ServicePlugin):
    metadata = PluginMetadata(name='zara-policy', version='0.1.0',
        description='Native Prolog output advice with an extensible policy knowledge base')
    enabled_by_default = False

    def __init__(self) -> None:
        self.client = PolicyClient()
        self.active = False

    def start(self, runtime) -> None:
        self.active = True
        registrar = getattr(runtime, 'register_agent_loop_advice', None)
        if registrar is None:
            logger.warning('[Policy] loop advice unavailable; draft-review tools remain available')
            return
        try:
            registrar('after', 90, self.after)
            registrar('before', 90, self.before)
        except RuntimeError:
            logger.warning('[Policy] loop advice unavailable; draft-review tools remain available')

    def stop(self) -> None:
        self.active = False

    def tools(self):
        def policy_advice(text: str) -> dict[str, Any]:
            """Review a draft using Prolog. Returns heuristic findings and corrective advice, not a truth verdict."""
            if not self.active:
                return self.client._unavailable('plugin_stopped')
            return self.client.advise(text)

        def policy_rules(offset: int = 0, limit: int = 16) -> dict[str, Any]:
            """Inspect the extensible Prolog policy catalog, its advice and source IDs; paginate with offset and limit."""
            if not self.active:
                return self.client._unavailable('plugin_stopped')
            return self.client.rules(offset=offset, limit=limit)

        return (StructuredTool.from_function(policy_advice), StructuredTool.from_function(policy_rules))

    async def before(self, *args, **kwargs) -> None:
        if not self.active:
            return
        state = kwargs.get('state', args[2] if len(args) > 2 else None)
        if not isinstance(state, dict) or not isinstance(state.get('messages'), list):
            return
        messages = state['messages']
        try:
            report = await asyncio.to_thread(self.client.advise, previous_output(messages))
        except (ValueError, TypeError):
            report = self.client._unavailable('input_limit')
        if self.active:
            state['messages'] = prepare_messages(messages, report, SystemMessage)

    def after(self, result) -> None:
        if isinstance(result, dict) and isinstance(result.get('messages'), list):
            result['messages'] = remove_advice(result['messages'])


def create_plugin() -> PolicyPlugin:
    return PolicyPlugin()
