"""Zara API v1 discovery entry for the stock risk and knowledge expert."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_VERSION = '0.1.0'


def create_plugin():
    from langchain_core.tools import StructuredTool
    from zara.plugins import PluginMetadata, ServicePlugin
    from zara_stock_expert.prolog import StockProlog
    from zara_stock_expert.service import StockService

    class ZaraStockExpertPlugin(StockService, ServicePlugin):
        metadata = PluginMetadata(
            name='zara-stock-expert', version=PLUGIN_VERSION, api_version='1',
            description='Persistent market KB, exact money arithmetic and explainable paper risk proposals',
        )

        def __init__(self):
            super().__init__()
            self._daily_database = None
            self._daily_namespace = None
            self._daily_prolog_enabled = False
            self._daily_instruments = ()

        @staticmethod
        def _plugin_section(configuration):
            section = configuration
            if isinstance(section, Mapping) and 'plugins' in section:
                plugins = section.get('plugins')
                if isinstance(plugins, Mapping):
                    section = plugins.get('zara-stock-expert', {})
            return section if isinstance(section, Mapping) else {}

        def start(self, runtime):
            section = self._plugin_section(runtime.configuration)
            market = section.get('market_data', {})
            instruments = market.get('instruments', {}) if isinstance(market, Mapping) else {}
            if isinstance(instruments, Mapping):
                names = tuple(sorted(name for name in instruments if isinstance(name, str)))
                if len(names) > 64:
                    raise ValueError('daily investor supports at most 64 configured instruments')
                self._daily_instruments = names
            self._daily_database = section.get('database')
            self._daily_namespace = section.get('namespace')
            self._daily_prolog_enabled = section.get('prolog_enabled', False) is True
            super().start(runtime)

        @staticmethod
        def _daily_error(stage, error):
            message = ' '.join(str(error).split())[:240]
            return {'stage': stage, 'type': type(error).__name__, 'message': message}

        def daily_investor(self) -> str:
            """Run the pre-authorized research-only daily cycle over configured instruments."""
            if not self._daily_prolog_enabled:
                raise RuntimeError('daily investor requires prolog_enabled=true')
            if not self._daily_instruments:
                raise RuntimeError('daily investor requires operator-configured market_data instruments')
            if not isinstance(self._daily_database, str) or not isinstance(self._daily_namespace, str):
                raise RuntimeError('daily investor requires the configured stock KB')

            policy = StockProlog(Path(self._daily_database), self._daily_namespace).authorize_daily_investor()
            status = json.loads(self.status())
            run_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
            reports = []

            for instrument in self._daily_instruments:
                report = {'instrument': instrument, 'errors': [], 'forecasts': []}
                try:
                    report['quote'] = json.loads(self.fetch_quote(instrument))
                except Exception as error:
                    report['errors'].append(self._daily_error('fetch_quote', error))

                try:
                    report['history'] = json.loads(self.history(instrument, limit=8))
                except Exception as error:
                    report['errors'].append(self._daily_error('history', error))

                models = {'models': [], 'truncated': False}
                try:
                    models = json.loads(self.neural_models(instrument, limit=2))
                    report['models'] = models
                except Exception as error:
                    report['errors'].append(self._daily_error('neural_models', error))

                if status.get('neural_enabled'):
                    for model in models.get('models', ()):
                        model_id = model.get('model_id') if isinstance(model, dict) else None
                        if not isinstance(model_id, str):
                            report['errors'].append({'stage': 'neural_forecast', 'type': 'ValueError',
                                                     'message': 'registered model card has no model_id'})
                            continue
                        try:
                            report['forecasts'].append(json.loads(self.neural_forecast(model_id)))
                        except Exception as error:
                            report['errors'].append(self._daily_error('neural_forecast', error))
                else:
                    report['forecast_status'] = 'neural research disabled; existing models were not executed'

                summary = {
                    'kind': 'daily_investor',
                    'run_at': run_at,
                    'instrument': instrument,
                    'quote_event_id': (report.get('quote') or {}).get('event_id'),
                    'forecast_event_ids': [item.get('event_id') for item in report['forecasts']
                                           if isinstance(item, dict) and isinstance(item.get('event_id'), str)],
                    'errors': report['errors'],
                    'execution_eligible': False,
                    'live_execution': False,
                }
                note = json.dumps(summary, sort_keys=True, separators=(',', ':'))
                digest = hashlib.sha256(note.encode('utf-8')).hexdigest()[:24]
                event_id = f'daily-investor:{instrument}:{digest}'
                try:
                    report['daily_note'] = json.loads(
                        self.remember_note(event_id, instrument, note, source='daily-investor')
                    )
                except Exception as error:
                    report['errors'].append(self._daily_error('daily_note', error))
                reports.append(report)

            return json.dumps({
                'kind': 'daily_investor_run',
                'run_at': run_at,
                'authorization': policy,
                'instruments': reports,
                'execution_eligible': False,
                'live_execution': False,
                'money_sizing': 'requires explicit account and risk inputs',
            }, sort_keys=True, allow_nan=False)

        def tools(self):
            definitions = (
                (self.neural_train, 'stock.neural_train', 'Train a bounded CPU MLP or causal TCN on trusted adjusted daily closes; persist a research model and chronological diagnostics, never an order.', True),
                (self.neural_forecast, 'stock.neural_forecast', 'Persist research log-return quantiles from a registered neural model. No guaranteed coverage, money arithmetic or trade execution.', True),
                (self.neural_models, 'stock.neural_models', 'List persisted neural model cards, provenance and baseline diagnostics without exposing weights.', False),
                (self.daily_investor, 'stock.daily_investor', 'Run the Prolog-authorized unattended research cycle over the operator-configured market-data allowlist. It may persist quotes, forecasts and a daily KB note, but cannot submit broker orders or use arbitrary instruments.', False),
                (self.status, 'stock.status', 'Report stock expert configuration and execution boundaries.', False),
                (self.fetch_quote, 'stock.fetch_quote', 'Fetch a configured instrument through the stock API adapter and persist the exact, source-labelled historical quote. No real-time or trade-execution claim.', True),
                (self.explain, 'stock.explain', 'Run the registered SWI-Prolog stock rules over a fresh risk assessment and return actual Prolog results. Requires prolog_enabled.', False),
                (self.report_quote, 'stock.report_quote', 'Persist a source-labelled but unverified quote report; never elevates model claims to provider evidence.', True),
                (self.remember_note, 'stock.remember_note', 'Persist a model note or hypothesis in the configured namespace, separate from market facts.', True),
                (self.history, 'stock.history', 'Retrieve bounded point-in-time market KB evidence, including optional immutable revisions.', False),
                (self.money, 'stock.money', 'Exact decimal-string add, fee-aware P&L, tick-rounded break-even and long-only position sizing. No floats or execution.', False),
                (self.evaluate, 'stock.evaluate', 'Explain paper-trade risk preflight against provider evidence; no strategy profitability claim and no broker order.', False),
            )
            return tuple(StructuredTool.from_function(func=function, name=name, description=description,
                         metadata={'zara_requires_approval': True} if writes else {})
                         for function, name, description, writes in definitions)

    return ZaraStockExpertPlugin()
