import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from concurrent.futures import Future
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from test_stock_expert import size

REQUIRE = os.environ.get('ZARA_STOCK_REQUIRE_INTEGRATION') == '1'


def available():
    try:
        return bool(shutil.which('swipl') and importlib.util.find_spec('zara_expert')
                    and importlib.util.find_spec('zara.plugins.builtin.market_data'))
    except (ImportError, ModuleNotFoundError):
        return False


@unittest.skipUnless(REQUIRE or available(), 'requires real Zara market client, zara-expert and SWI-Prolog')
class RealMarketExpertIntegrationTest(unittest.TestCase):
    def test_provider_tool_kb_money_and_prolog_on_real_runtime(self):
        from zara.plugins import PluginRuntime, RuntimeStatus
        from zara.runtime.bridge import RuntimeEventBus
        import zara.plugins.builtin.market_data
        import zara_expert.backend
        self.assertIsNotNone(shutil.which('swipl'))
        path = Path(__file__).resolve().parents[1] / 'zara-plugin' / 'zara_stock_expert_entrypoint.py'
        spec = importlib.util.spec_from_file_location('real_stock_entry', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        plugin = module.create_plugin()
        errors = []
        bus = RuntimeEventBus()
        quote = {'Global Quote': {
            '01. symbol': 'EXAMPLE', '02. open': '99.00', '03. high': '101.00',
            '04. low': '98.00', '05. price': '100.000000000000', '06. volume': '1000',
            '07. latest trading day': '2026-09-16', '08. previous close': '99.00',
            '09. change': '1.00', '10. change percent': '1.010101%'}}
        with tempfile.TemporaryDirectory() as root:
            configuration = {'database': str(Path(root) / 'private' / 'market.db'),
                'namespace': 'integration', 'prolog_enabled': True, 'neural': {'enabled': True},
                'market_data': {'instruments': {'XNAS:EXAMPLE': {'symbol': 'EXAMPLE', 'currency': 'USD'}}}}
            runtime = PluginRuntime(plugin_name='zara-stock-expert', configuration=configuration,
                status_provider=lambda: RuntimeStatus(state='running', alive=True, thread_id=None),
                dispatcher=lambda command: Future(), subscriber=bus.subscribe, failure_callback=errors.append)
            try:
                with patch.dict(os.environ, {'ALPHAVANTAGE_API_KEY': 'fixture-not-a-real-key'}), \
                        patch('zara_stock_expert.market.request_json', return_value=quote) as transport:
                    plugin.start(runtime)
                    tools = {tool.name: tool for tool in plugin.tools()}
                    self.assertTrue(tools['stock.fetch_quote'].metadata['zara_requires_approval'])
                    self.assertFalse((tools['stock.daily_investor'].metadata or {}).get('zara_requires_approval', False))
                    first = json.loads(tools['stock.fetch_quote'].invoke({'instrument': 'XNAS:EXAMPLE'}))
                    second = json.loads(tools['stock.fetch_quote'].invoke({'instrument': 'XNAS:EXAMPLE'}))
                    self.assertEqual(first, second)
                    self.assertEqual(first['payload']['price'], '100.000000000000')
                    self.assertEqual(first['provenance'], 'provider_adapter')
                    self.assertEqual(transport.call_count, 2)
                    self.assertIn('function=GLOBAL_QUOTE', transport.call_args.args[0])
                    result = json.loads(tools['stock.explain'].invoke({
                        'instrument': 'XNAS:EXAMPLE', 'sizing_json': json.dumps(size())}))
                    self.assertEqual(result['engine'], 'swipl')
                    self.assertEqual(result['assessment']['decision'], 'blocked')
                    self.assertIn('not_realtime', result['prolog']['results'][0])
                    self.assertIn('explanation(blocked,', result['prolog']['results'][0].replace(' ', ''))
                    self.assertTrue(json.loads(plugin.status())['prolog_registered'])
                    from test_neural import bars
                    for observation in bars(now=datetime.now(timezone.utc)):
                        plugin.ingest_bar(observation)
                    card = json.loads(tools['stock.neural_train'].invoke({'instrument': 'XNAS:EXAMPLE',
                        'source': 'synthetic', 'epochs': 3, 'folds': 1, 'lookback': 8}))
                    forecast = json.loads(tools['stock.neural_forecast'].invoke({'model_id': card['model_id']}))
                    self.assertFalse(forecast['payload']['execution_eligible'])
                    self.assertEqual(forecast['provenance'], 'model_forecast')
                    models = json.loads(tools['stock.neural_models'].invoke({'instrument': 'XNAS:EXAMPLE'}))
                    self.assertEqual(len(models['models']), 1)
                    daily = json.loads(tools['stock.daily_investor'].invoke({}))
                    self.assertTrue(daily['authorization']['authorized'])
                    self.assertEqual(daily['authorization']['mode'], 'research')
                    self.assertFalse(daily['execution_eligible'])
                    self.assertFalse(daily['live_execution'])
                    self.assertEqual(len(daily['instruments']), 1)
                    self.assertEqual(daily['instruments'][0]['instrument'], 'XNAS:EXAMPLE')
                    self.assertEqual(daily['instruments'][0]['daily_note']['provenance'], 'model_note')
                    self.assertGreaterEqual(transport.call_count, 3)
                    exact = json.loads(tools['stock.money'].invoke({'operation': 'add', 'arguments_json':
                        '{"left":{"amount":"0.1","currency":"USD"},"right":{"amount":"0.2","currency":"USD"}}'}))
                    self.assertEqual(exact['amount'], '0.30')
                    self.assertEqual(json.loads(tools['stock.evaluate'].invoke({'instrument': 'XNAS:EXAMPLE',
                        'sizing_json': json.dumps(size())}))['decision'], 'blocked')
            finally:
                plugin.stop()
                runtime._shutdown()
            self.assertEqual(errors, [])
