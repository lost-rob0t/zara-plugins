import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from zara_stock_expert.service import StockService
from test_service import TestWorker


class RuntimeConfigurationTest(unittest.TestCase):
    def test_plugin_local_configuration_starts_storage(self):
        with tempfile.TemporaryDirectory() as root:
            worker_errors = []
            def start_worker(name, target):
                worker = TestWorker(target)
                worker_errors.append(worker.errors)
                return worker
            service = StockService()
            try:
                service.start(SimpleNamespace(configuration={
                    'database': str(Path(root) / 'private' / 'stock.db'),
                    'namespace': 'test'}, start_worker=start_worker))
                self.assertTrue(json.loads(service.status())['configured'])
                service.remember_note('one', 'XNAS:EXAMPLE', 'research only')
                self.assertEqual(len(json.loads(service.history('XNAS:EXAMPLE'))['records']), 1)
            finally:
                service.stop()
            self.assertEqual(worker_errors, [[]])


class MarketIntegrationTest(unittest.TestCase):
    def test_adapter_preserves_decimal_text_and_day_precision(self):
        from zara_stock_expert.market import AlphaVantageSource
        class Client:
            def __init__(self, config, *, request_json):
                pass
            def quote(self, symbol):
                return {'provider': 'alpha_vantage', 'symbol': symbol,
                        'price': self._number('100.123456789012'),
                        'trading_day': '2026-09-16'}
        config = {'instruments': {'XNAS:EXAMPLE': {'symbol': 'EXAMPLE', 'currency': 'USD'}}}
        source = AlphaVantageSource(config, client_class=Client, config_factory=lambda values: values)
        record = source.fetch('XNAS:EXAMPLE')
        self.assertEqual(record['price'], '100.123456789012')
        self.assertEqual(record['feed'], 'historical')
        self.assertEqual(record['timestamp_precision'], 'day')
        self.assertEqual(record['trading_day'], '2026-09-16')
        self.assertEqual(record['event_id'], source.fetch('XNAS:EXAMPLE')['event_id'])

    def test_float_and_wrong_symbol_do_not_reach_kb(self):
        from zara_stock_expert.market import AlphaVantageSource
        for result in ({'price': 100.0, 'symbol': 'EXAMPLE'},
                       {'price': '100', 'symbol': 'WRONG'}):
            class Client:
                def __init__(self, *args, **kwargs):
                    pass
                def quote(self, symbol):
                    return dict(provider='alpha_vantage', trading_day='2026-09-16', **result)
            source = AlphaVantageSource({'instruments': {
                'XNAS:EXAMPLE': {'symbol': 'EXAMPLE', 'currency': 'USD'}}},
                client_class=Client, config_factory=lambda values: values)
            with self.subTest(result=result), self.assertRaises(ValueError):
                source.fetch('XNAS:EXAMPLE')

class IntegrationFailurePathsTest(unittest.TestCase):
    def source(self, quote_result=None, error=None):
        from zara_stock_expert.market import AlphaVantageSource
        class Client:
            calls = 0
            def __init__(self, *args, **kwargs):
                pass
            def quote(self, symbol):
                self.calls += 1
                if error is not None:
                    raise error
                return quote_result or {'provider': 'alpha_vantage', 'symbol': symbol,
                    'price': '100.00', 'trading_day': '2026-09-16'}
        return AlphaVantageSource({'instruments': {'XNAS:EXAMPLE': {
            'symbol': 'EXAMPLE', 'currency': 'USD'}}},
            client_class=Client, config_factory=lambda values: values)

    def test_invalid_mapping_rejected_before_client_creation(self):
        from zara_stock_expert.market import AlphaVantageSource
        invalid = [None, {}, {'instruments': {}}, {'instruments': []},
                   {'instruments': {'EXAMPLE': {'symbol': 'EXAMPLE', 'currency': 'USD'}}},
                   {'instruments': {'XNAS:EXAMPLE': {'symbol': 'EXAMPLE', 'currency': 'usd'}}},
                   {'instruments': {'XNAS:EXAMPLE': {'symbol': 'EXAMPLE', 'currency': 'USD', 'extra': 1}}}]
        valid = {'instruments': {'XNAS:EXAMPLE': {'symbol': 'EXAMPLE', 'currency': 'USD'}}}
        invalid.extend(dict(valid, **extra) for extra in (
            {'api_key': 'never-store-this'}, {'endpoint': 'http://localhost/'},
            {'timeout_seconds': True}, {'timeout_seconds': 4}, {'api_key_env': 'BAD KEY'}))
        for config in invalid:
            with self.subTest(config=config), self.assertRaises(ValueError):
                AlphaVantageSource(config, client_class=object, config_factory=lambda value: value)

    def test_unknown_instrument_makes_no_provider_request(self):
        source = self.source()
        with self.assertRaises(ValueError):
            source.fetch('XNAS:OTHER')
        self.assertEqual(source._client.calls, 0)

    def test_provider_error_is_redacted_and_lock_is_released(self):
        source = self.source(error=RuntimeError('https://provider/?apikey=TOP-SECRET'))
        for _ in range(2):
            with self.assertRaises(RuntimeError) as raised:
                source.fetch('XNAS:EXAMPLE')
            self.assertNotIn('TOP-SECRET', str(raised.exception))
        self.assertEqual(source._client.calls, 2)

    def test_one_request_in_flight(self):
        source = self.source()
        source._lock.acquire()
        try:
            with self.assertRaisesRegex(RuntimeError, 'in flight'):
                source.fetch('XNAS:EXAMPLE')
            self.assertEqual(source._client.calls, 0)
        finally:
            source._lock.release()

    def test_invalid_dates_and_prices(self):
        for changes in ({'trading_day': '2026-02-30'}, {'trading_day': '20260916'},
                        {'trading_day': None}, {'price': 'NaN'}, {'price': '-1'},
                        {'price': '0'}, {'price': '1e2'}):
            quote = dict(provider='alpha_vantage', symbol='EXAMPLE', price='100', trading_day='2026-09-16')
            quote.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.source(quote_result=quote).fetch('XNAS:EXAMPLE')

    def test_fetch_persists_once_and_reopens_with_day_semantics(self):
        from test_stock_expert import size
        source = self.source()
        with tempfile.TemporaryDirectory() as root:
            config = {'database': str(Path(root) / 'private' / 'market.db'), 'namespace': 'test',
                      'market_data': {'instruments': {}}}
            runtime = SimpleNamespace(configuration=config, start_worker=lambda name, target: TestWorker(target))
            service = StockService()
            try:
                with patch('zara_stock_expert.market.AlphaVantageSource', return_value=source):
                    service.start(runtime)
                first = json.loads(service.fetch_quote('XNAS:EXAMPLE'))
                self.assertEqual(first, json.loads(service.fetch_quote('XNAS:EXAMPLE')))
                self.assertEqual(first['provenance'], 'provider_adapter')
                self.assertEqual(first['payload']['timestamp_precision'], 'day')
                decision = json.loads(service.evaluate('XNAS:EXAMPLE', json.dumps(size())))
                self.assertEqual(decision['decision'], 'blocked')
                self.assertTrue({'not_realtime', 'imprecise_quote_time', 'unknown_price_adjustment'}
                                <= set(decision['blockers']))
                with self.assertRaises(RuntimeError):
                    service.explain('XNAS:EXAMPLE', json.dumps(size()))
            finally:
                service.stop()
            service = StockService()
            try:
                runtime.configuration = {key: value for key, value in config.items() if key != 'market_data'}
                service.start(runtime)
                records = json.loads(service.history('XNAS:EXAMPLE'))['records']
                self.assertEqual(records, [first])
                self.assertFalse(json.loads(service.status())['market_data_configured'])
                with self.assertRaises(RuntimeError):
                    service.fetch_quote('XNAS:EXAMPLE')
            finally:
                service.stop()

    def test_day_semantics_cannot_be_relabelled_realtime(self):
        from zara_stock_expert.domain import StockExpert
        observation = self.source().fetch('XNAS:EXAMPLE')
        with tempfile.TemporaryDirectory() as root:
            expert = StockExpert(Path(root) / 'private' / 'market.db', 'test')
            try:
                for changes in ({'feed': 'realtime'}, {'effective_at': '2026-09-16T10:00:00+00:00'},
                                {'timestamp_precision': 'instant'}, {'trading_day': '2026-09-15'}):
                    with self.subTest(changes=changes), self.assertRaises(ValueError):
                        expert.ingest_quote(dict(observation, **changes))
                self.assertEqual(expert.history('XNAS:EXAMPLE')['records'], [])
            finally:
                expert.close()

    def test_bad_prolog_configuration_and_registration_failure_are_not_ready(self):
        for setting in ('true', True):
            with tempfile.TemporaryDirectory() as root:
                service = StockService()
                runtime = SimpleNamespace(configuration={'database': str(Path(root) / 'private' / 'market.db'),
                    'namespace': 'test', 'prolog_enabled': setting},
                    start_worker=lambda name, target: TestWorker(target))
                try:
                    with patch('zara_stock_expert.prolog.StockProlog', side_effect=RuntimeError('missing SWI')):
                        with self.assertRaises((ValueError, RuntimeError)):
                            service.start(runtime)
                    self.assertFalse(json.loads(service.status())['configured'])
                finally:
                    service.stop()


class TransportTest(unittest.TestCase):
    def response(self, body, status=200):
        import io
        class Response(io.BytesIO):
            pass
        response = Response(body)
        response.status = status
        return response

    def test_bounded_json_transport(self):
        from zara_stock_expert.market import request_json
        for body in (b'{"price":"100.10"}', b'{"x":1,"x":2}', b'{"x":NaN}',
                     b'[]', b'\xff', b'x' * 16385):
            with self.subTest(body=body[:30]), patch('urllib.request.build_opener') as opener:
                opener.return_value.open.return_value = self.response(body)
                if body == b'{"price":"100.10"}':
                    self.assertEqual(request_json('https://www.alphavantage.co/query?apikey=fixture', 3),
                                     {'price': '100.10'})
                else:
                    with self.assertRaises(RuntimeError):
                        request_json('https://www.alphavantage.co/query?apikey=fixture', 3)

    def test_endpoint_and_redirect_rejections(self):
        from zara_stock_expert.market import NoRedirect, request_json
        for endpoint in ('http://www.alphavantage.co/query', 'https://evil.example/query',
                         'https://user:secret@www.alphavantage.co/query',
                         'https://www.alphavantage.co/elsewhere', 'https://www.alphavantage.co/query#x'):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                request_json(endpoint, 3)
        with self.assertRaises(ValueError):
            NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.example/')

    def test_non_success_transport_is_redacted(self):
        from zara_stock_expert.market import request_json
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = OSError('apikey=TOP-SECRET')
            with self.assertRaises(RuntimeError) as raised:
                request_json('https://www.alphavantage.co/query', 3)
            self.assertNotIn('TOP-SECRET', str(raised.exception))


class PrologRegistrationTest(unittest.TestCase):
    def host(self, result=None):
        class Host:
            def __init__(self, backend, **options):
                self.options = options
                self.calls = []
            def register(self, namespace, files):
                self.registration = (namespace, files)
            def explain(self, namespace, goal):
                self.calls.append((namespace, goal))
                return result if result is not None else {'ok': True, 'results': ['fixture'], 'trace': ['fixture']}
        return Host

    def test_automatic_registration_and_safe_goal(self):
        from zara_stock_expert.prolog import StockProlog
        expert = StockProlog(Path('/tmp/private/test.db'), 'my:namespace', host_factory=self.host())
        namespace, files = expert.host.registration
        self.assertEqual(namespace, expert.namespace)
        self.assertTrue(files[0].is_file())
        self.assertEqual(expert.host.options['max_results'], 1)
        self.assertEqual(expert.host.options['query_timeout_seconds'], 1.0)
        result = expert.explain({'mode': 'paper', 'blockers': ['not_realtime']})
        self.assertEqual(expert.host.calls[0][1],
                         'stock_trade_explain(assessment(paper,[not_realtime]),Explanation)')
        self.assertEqual(result['prolog']['results'], ['fixture'])
        self.assertFalse(result['executable'])
        for assessment in ({'mode': 'paper),halt', 'blockers': []},
                           {'mode': 'paper', 'blockers': ['x),halt']},
                           {'mode': 'paper', 'blockers': ['x'] * 33}):
            with self.assertRaises(ValueError):
                expert.explain(assessment)
        self.assertEqual(len(expert.host.calls), 1)

    def test_no_solution_is_failure_not_python_fallback(self):
        from zara_stock_expert.prolog import StockProlog
        expert = StockProlog(Path('/tmp/private/test.db'), 'test',
                            host_factory=self.host({'ok': True, 'results': []}))
        with self.assertRaises(RuntimeError):
            expert.explain({'mode': 'paper', 'blockers': []})


if __name__ == '__main__':
    unittest.main()
