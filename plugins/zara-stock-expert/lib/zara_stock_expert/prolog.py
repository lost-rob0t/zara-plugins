from __future__ import annotations

import hashlib
import re
from pathlib import Path

REASON = re.compile(r'[a-z][a-z0-9_]{0,63}\Z')


class StockProlog:
    """Register bundled stock rules with the existing bounded Zara ExpertHost."""

    def __init__(self, database: Path, namespace: str, *, host_factory=None, backend=None) -> None:
        if host_factory is None:
            try:
                from zara_expert.backend import SwiplBackend
                from zara_expert.domain import ExpertHost
            except ImportError:
                raise RuntimeError('Prolog integration requires the zara-expert library') from None
            if not SwiplBackend.available():
                raise RuntimeError('Prolog integration requires SWI-Prolog on PATH')
            host_factory = ExpertHost
            backend = SwiplBackend(output_limit=16384)
        identity = str(database.expanduser().resolve()) + ':' + namespace
        self.namespace = 'stock-' + hashlib.sha256(identity.encode()).hexdigest()[:32]
        self.host = host_factory(backend, state_root=database.expanduser().parent / 'prolog',
                                 query_timeout_seconds=1.0, max_results=1)
        self.host.register(self.namespace, [Path(__file__).with_name('stock_host.pl')])

    def explain(self, assessment: dict) -> dict:
        mode, blockers = assessment.get('mode'), assessment.get('blockers')
        if (mode not in ('paper', 'live') or not isinstance(blockers, list)
                or len(blockers) > 32 or any(not isinstance(reason, str) or not REASON.fullmatch(reason)
                                           for reason in blockers)):
            raise ValueError('invalid stock assessment for Prolog')
        reasons = ','.join(blockers)
        goal = f'stock_trade_explain(assessment({mode},[{reasons}]),Explanation)'
        result = self.host.explain(self.namespace, goal)
        if (not isinstance(result, dict) or result.get('ok') is not True
                or not isinstance(result.get('results'), list) or len(result['results']) != 1
                or not isinstance(result['results'][0], str)):
            raise RuntimeError('stock Prolog expert returned no unique explanation')
        return {'engine': 'swipl', 'namespace': self.namespace,
                'assessment': assessment, 'prolog': result, 'executable': False}
