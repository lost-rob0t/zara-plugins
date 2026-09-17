from __future__ import annotations

import json
import os
from pathlib import Path

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .session import PrologSession

PLUGIN_VERSION = '0.1.0'
APPROVAL_METADATA = {'zara_requires_approval': True}


class ZaraPrologPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name='zara-prolog', version=PLUGIN_VERSION, api_version='1',
        description='First-class operator Prolog queries, executable config, reload and catalogue',
    )

    def __init__(self, session=None):
        home = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
        self.session = session if session is not None else PrologSession(
            home / 'zarathushtra' / 'plugins' / 'zara-prolog')
        self._error = None

    def start(self, runtime) -> None:
        try:
            self.session.start()
            self._error = None
        except Exception:
            self._error = 'prolog-startup-failed'

    def stop(self) -> None:
        self.session.stop()

    def status(self) -> str:
        return json.dumps({'status': 'ready' if self.session.ready else 'unavailable',
                           'backend': 'zara.prolog_engine.PrologEngine', 'scope': 'operator',
                           'sandboxed': False, 'error': self._error})

    def query(self, goal: str, max_solutions: int = 16) -> str:
        return json.dumps(self.session.query(goal, max_solutions))

    def reload(self) -> str:
        return json.dumps(self.session.reload())

    def catalog(self) -> str:
        return json.dumps(self.session.query('zara_prolog_session:catalog(Name, Arity)', 64))

    def tools(self):
        return (
            StructuredTool.from_function(func=self.status, name='prolog.status',
                description='Report the first-class Prolog runtime state and operator-only trust boundary.'),
            StructuredTool.from_function(func=self.query, name='prolog.query',
                description='Execute operator-approved Prolog in the user configuration module. This is arbitrary code, not a sandbox; time and inference limits are cooperative.',
                metadata=APPROVAL_METADATA),
            StructuredTool.from_function(func=self.reload, name='prolog.reload',
                description='Reload operator-owned executable Prolog config. Directives can execute code; reload is not transactional.',
                metadata=APPROVAL_METADATA),
            StructuredTool.from_function(func=self.catalog, name='prolog.catalog',
                description='List up to 64 predicate names and arities from the operator Prolog module.'),
        )


def create_plugin():
    return ZaraPrologPlugin()
