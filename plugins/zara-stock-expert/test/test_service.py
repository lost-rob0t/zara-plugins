import importlib.util
import json
import queue
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from zara_stock_expert.service import StockService, MAX_MAILBOX, decode


class TestWorker:
    def __init__(self, target):
        self.stop_event = threading.Event()
        self.errors = []
        def run():
            try:
                target(self.stop_event)
            except Exception as error:
                self.errors.append(error)
        self.thread = threading.Thread(target=run)
        self.thread.start()

    def request_stop(self):
        self.stop_event.set()

    def join(self, timeout=None):
        self.thread.join(timeout)

    @property
    def is_alive(self):
        return self.thread.is_alive()


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = StockService()
        self.workers = []
        def start_worker(name, target):
            worker = TestWorker(target)
            self.workers.append(worker)
            return worker
        self.runtime = SimpleNamespace(configuration={'plugins': {'zara-stock-expert': {
            'database': str(Path(self.tmp.name) / 'private' / 'market.sqlite3'), 'namespace': 'test'}}},
            start_worker=start_worker)

    def tearDown(self):
        self.service.stop()
        self.tmp.cleanup()

    def test_lifecycle_and_provider_adapter(self):
        self.service.start(self.runtime)
        observation = dict(event_id='q', instrument='XNAS:EXAMPLE', source='fixture',
                           effective_at=datetime.now(timezone.utc).isoformat(), price='100',
                           currency='USD', adjustment='raw', feed='realtime', price_kind='last')
        self.assertEqual(self.service.ingest_quote(observation)['provenance'], 'provider_adapter')
        self.assertEqual(len(json.loads(self.service.history('XNAS:EXAMPLE'))['records']), 1)
        self.service.stop()
        self.assertFalse(self.workers[0].is_alive)
        self.assertEqual(self.workers[0].errors, [])
        with self.assertRaises(RuntimeError):
            self.service.history('XNAS:EXAMPLE')

    def test_concurrent_same_note_is_exactly_once(self):
        self.service.start(self.runtime)
        with ThreadPoolExecutor(max_workers=8) as pool:
            outputs = list(pool.map(lambda _: self.service.remember_note('n', 'XNAS:EXAMPLE', 'hypothesis'), range(16)))
        self.assertEqual(len(set(outputs)), 1)
        self.assertEqual(len(json.loads(self.service.history('XNAS:EXAMPLE'))['records']), 1)

    def test_unconfigured_and_pure_money(self):
        self.service.start(SimpleNamespace(configuration={}))
        self.assertFalse(json.loads(self.service.status())['configured'])
        result = self.service.money('add', '{"left":{"amount":"0.1","currency":"USD"},"right":{"amount":"0.2","currency":"USD"}}')
        self.assertEqual(json.loads(result)['amount'], '0.30')
        with self.assertRaises(RuntimeError):
            self.service.remember_note('n', 'XNAS:EXAMPLE', 'hypothesis')

    def test_invalid_configuration(self):
        self.runtime.configuration['plugins']['zara-stock-expert']['max_quote_age_seconds'] = True
        with self.assertRaises(ValueError):
            self.service.start(self.runtime)
        self.assertEqual(self.workers, [])

    def test_bounded_mailbox_and_unknown_operation(self):
        self.service._accepting = True
        for _ in range(MAX_MAILBOX):
            self.service._queue.put_nowait(None)
        with self.assertRaisesRegex(RuntimeError, 'full'):
            self.service.history('XNAS:EXAMPLE')
        with self.assertRaises(ValueError):
            self.service._ask('__getattribute__', {})
        self.service._accepting = False

    def test_json_boundary(self):
        for value in ('{"x":1,"x":2}', '{"x":NaN}', '[]', 'x' * 16385):
            with self.subTest(value=value[:40]), self.assertRaises(ValueError):
                decode(value)

    def test_failure_start_stops_owner(self):
        self.runtime.configuration['plugins']['zara-stock-expert']['database'] = 'relative.sqlite3'
        with self.assertRaises(ValueError):
            self.service.start(self.runtime)
        self.assertFalse(self.workers[0].is_alive)


class RealZaraCompatibilityTest(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('zara') and importlib.util.find_spec('langchain_core'),
                         'real Zara and langchain-core are not installed')
    def test_real_tool_contract(self):
        path = Path(__file__).resolve().parents[1] / 'zara-plugin' / 'zara_stock_expert_entrypoint.py'
        spec = importlib.util.spec_from_file_location('stock_entry', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        plugin = module.create_plugin()
        tools = {tool.name: tool for tool in plugin.tools()}
        self.assertEqual(len(tools), 11)
        self.assertNotIn('stock.ingest_quote', tools)
        self.assertNotIn('stock.ingest_bar', tools)
        self.assertTrue(tools['stock.neural_train'].metadata['zara_requires_approval'])
        self.assertTrue(tools['stock.neural_forecast'].metadata['zara_requires_approval'])
        self.assertTrue(tools['stock.fetch_quote'].metadata['zara_requires_approval'])
        self.assertTrue(tools['stock.report_quote'].metadata['zara_requires_approval'])
        self.assertTrue(tools['stock.remember_note'].metadata['zara_requires_approval'])
        result = tools['stock.money'].invoke({'operation': 'add', 'arguments_json':
            '{"left":{"amount":"0.1","currency":"USD"},"right":{"amount":"0.2","currency":"USD"}}'})
        self.assertEqual(json.loads(result)['amount'], '0.30')
        plugin.stop()
