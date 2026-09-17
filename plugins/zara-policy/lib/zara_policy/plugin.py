from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .backend import PolicyBackend
from .review import ReviewModel

PLUGIN_VERSION = '0.1.0'


class ZaraPolicyPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name='zara-policy', version=PLUGIN_VERSION, api_version='1',
        description='Prolog-authored response quality advice with an extensible default KB',
    )

    def __init__(self, backend=None):
        home = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
        self.backend = backend if backend is not None else PolicyBackend(
            home / 'zarathushtra' / 'plugins' / 'zara-policy')
        self._started = False
        self._registered_runtime = None
        self._advice_status = 'not-started'

    def start(self, runtime) -> None:
        if self._started:
            return
        try:
            self.backend.start()
        except Exception:
            self._advice_status = 'backend-unavailable'
            return
        self._started = True
        try:
            if self._registered_runtime is not runtime:
                runtime.register_agent_loop_advice('around', 40, self.advise)
                self._registered_runtime = runtime
            self._advice_status = 'active'
        except Exception as error:
            self._advice_status = ('hooks-disabled' if type(error).__name__ in
                {'HookRegistrationError', 'PermissionError'} else 'advice-api-unavailable')

    def stop(self) -> None:
        self._started = False
        self.backend.stop()
        self._advice_status = 'stopped'

    async def advise(self, next_loop, llm_client, tool_registry, state, **kwargs):
        if not self._started or self.backend.mode == 'off':
            return await next_loop(llm_client, tool_registry, state, **kwargs)
        return await next_loop(ReviewModel(llm_client, self.backend), tool_registry, state, **kwargs)

    def status(self) -> str:
        return json.dumps({
            'status': 'ready' if self.backend.ready else 'unavailable',
            'advice': self._advice_status, 'mode': self.backend.mode,
            'matched_rules': list(self.backend.last_rule_ids),
            'match_count': self.backend.match_count,
            'scope': 'operator', 'heuristic': True,
        })

    def inspect(self, text: str) -> str:
        findings = self.backend.inspect(text)
        return json.dumps({'findings': [asdict(item) for item in findings], 'heuristic': True})

    def tools(self):
        return (
            StructuredTool.from_function(func=self.status, name='policy.status',
                description='Report response policy availability, mode and rule IDs without transcript content.'),
            StructuredTool.from_function(func=self.inspect, name='policy.inspect',
                description='Inspect text using the operator-owned Prolog policy KB. Matches are review signals, not proof of failure; this tool does not rewrite or execute text.'),
        )


def create_plugin():
    return ZaraPolicyPlugin()
