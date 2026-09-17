import copy
import importlib.util
import json
import math
import os
import sqlite3
import subprocess
import threading
import time
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from zara_stock_expert.domain import StockExpert
from zara_stock_expert.neural import config, dataset, folds, fingerprint
from zara_stock_expert.neural_store import NeuralStore
from zara_stock_expert.service import StockService
from test_service import TestWorker

HAS_TORCH = bool(importlib.util.find_spec('torch'))
REQUIRE = os.environ.get('ZARA_STOCK_REQUIRE_NEURAL') == '1'
NOW = datetime(2026, 9, 17, tzinfo=timezone.utc)


def bars(count=240, now=NOW):
    price = 100.0
    observations = []
    for i in range(count):
        price *= math.exp(0.002 * math.sin(i * 0.35) + 0.0001)
        close = f'{price:.8f}'
        observations.append(dict(event_id=f'bar-{i}', instrument='XNAS:EXAMPLE', source='synthetic',
            effective_at=(now - timedelta(days=count - i)).isoformat(),
            close=close, currency='USD', adjustment='split', interval='1d',
            session_index=i))
    return observations


def snapshot(count=240):
    source = bars(count)
    return dict(instrument='XNAS:EXAMPLE', source='synthetic', currency='USD', adjustment='split',
        interval='1d', known_at=NOW.isoformat(), history_truncated=False,
        records=[dict(event_id=b['event_id'], effective_at=b['effective_at'], recorded_at=NOW.isoformat(),
                      close=b['close'], session_index=b['session_index']) for b in source])


class NeuralPlanTest(unittest.TestCase):
    def test_configuration_rejects_unbounded_or_unknown_options(self):
        for values in ({'architecture': 'magic'}, {'epochs': True}, {'horizon': 0},
                       {'lookback': 65}, {'epochs': 201}, {'seed': -1}, {'folds': 9},
                       {'learning_rate': '100'}, {'model_path': '/tmp/model.pkl'}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                config(values)
        self.assertEqual(config({})['architecture'], 'tcn')

    def test_features_and_labels_have_exact_endpoints(self):
        data = dataset(snapshot(), config({'lookback': 8, 'horizon': 5}))
        self.assertEqual(len(data['x'][0]), 8)
        prices = [float(row['close']) for row in snapshot()['records']]
        self.assertAlmostEqual(data['y'][0], math.log(prices[13] / prices[8]))
        self.assertAlmostEqual(data['x'][0][-1], math.log(prices[8] / prices[7]))
        self.assertEqual(data['origins'][0], 8)
        self.assertEqual(data['label_ends'][0], 13)

    def test_walk_forward_purges_all_boundary_labels(self):
        options = config({'horizon': 5})
        data = dataset(snapshot(), options)
        plans = folds(len(data['y']), options)
        self.assertEqual(len(plans), 3)
        for plan in plans:
            for left, right in (('train', 'validation'), ('validation', 'calibration'),
                                ('calibration', 'test')):
                self.assertLess(data['label_ends'][plan[left][1] - 1],
                                data['origins'][plan[right][0]])
        self.assertLessEqual(plans[0]['test'][1], plans[1]['test'][0])

    def test_future_tail_cannot_change_past_features_or_labels(self):
        old = dataset(snapshot(), config({}))
        changed = snapshot()
        changed['records'][-1]['close'] = '99999.00'
        new = dataset(changed, config({}))
        self.assertEqual(old['x'][:-1], new['x'][:-1])
        self.assertEqual(old['y'][:-1], new['y'][:-1])

    def test_dataset_rejects_bad_semantics(self):
        for modify in (
            lambda s: s.update(adjustment='unknown'),
            lambda s: s.update(adjustment='raw'),
            lambda s: s['records'][1].update(session_index=88),
            lambda s: s['records'][1].update(close=100.0),
            lambda s: s['records'][1].update(close='0'),
            lambda s: s['records'][1].update(effective_at=s['records'][0]['effective_at']),
            lambda s: s['records'][1].update(recorded_at='2099-01-01T00:00:00+00:00'),
            lambda s: s.update(records=s['records'] * 5),
        ):
            value = snapshot()
            modify(value)
            with self.subTest(value=str(value)[:100]), self.assertRaises(ValueError):
                dataset(value, config({}))

    def test_insufficient_samples_fail_instead_of_shuffled_split(self):
        with self.assertRaisesRegex(ValueError, 'insufficient'):
            folds(40, config({}))

    def test_fingerprint_changes_with_revision(self):
        value = snapshot()
        before = fingerprint(value)
        value['records'][0]['event_id'] = 'corrected'
        self.assertNotEqual(before, fingerprint(value))


class NeuralStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.expert = StockExpert(Path(self.tmp.name) / 'private' / 'stock.db', 'one', clock=lambda: NOW)
        self.store = NeuralStore(self.expert)

    def tearDown(self):
        self.expert.close()
        self.tmp.cleanup()

    def test_trusted_bar_ingest_is_idempotent_and_currency_preserving(self):
        bar = bars()[0]
        first = self.store.ingest_bar(bar)
        self.assertEqual(first, self.store.ingest_bar(bar))
        self.assertEqual(first['provenance'], 'provider_adapter')
        self.assertEqual(first['payload']['close'], bar['close'])
        self.assertEqual(self.expert.history('XNAS:EXAMPLE')['records'][0]['kind'], 'bar')

    def test_bar_boundary_rejects_float_unknown_adjustment_and_extra_fields(self):
        for change in ({'close': 10.0}, {'adjustment': 'unknown'}, {'interval': 'tick'},
                       {'session_index': True}, {'source': 'bad source'}, {'provenance': 'provider_adapter'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.store.ingest_bar(dict(bars()[0], **change))

    def test_snapshot_filters_source_before_limit_and_never_uses_model_notes(self):
        for observation in bars(100):
            self.store.ingest_bar(observation)
        self.expert.remember_note('n', 'XNAS:EXAMPLE', 'Fake close 1000000', 'llm')
        foreign = dict(bars(1)[0], source='other', event_id='foreign', close='999')
        self.store.ingest_bar(foreign)
        result = self.store.snapshot('XNAS:EXAMPLE', 'synthetic', limit=80)
        self.assertEqual(len(result['records']), 80)
        self.assertTrue(result['history_truncated'])
        self.assertNotIn('foreign', [r['event_id'] for r in result['records']])

    def test_snapshot_correction_respects_knowledge_cutoff(self):
        observation = bars(1)[0]
        self.store.ingest_bar(observation)
        self.expert.clock = lambda: NOW + timedelta(hours=1)
        self.store.ingest_bar(dict(observation, event_id='revision', close='101', supersedes=observation['event_id']))
        past = self.store.snapshot('XNAS:EXAMPLE', 'synthetic', known_at=NOW.isoformat())
        current = self.store.snapshot('XNAS:EXAMPLE', 'synthetic')
        self.assertEqual(past['records'][0]['event_id'], observation['event_id'])
        self.assertEqual(current['records'][0]['event_id'], 'revision')

    def test_namespace_isolation(self):
        self.store.ingest_bar(bars(1)[0])
        other = StockExpert(Path(self.tmp.name) / 'private' / 'stock.db', 'two', clock=lambda: NOW)
        try:
            self.assertEqual(NeuralStore(other).snapshot('XNAS:EXAMPLE', 'synthetic')['records'], [])
        finally:
            other.close()


@unittest.skipUnless(HAS_TORCH or REQUIRE, 'optional PyTorch is not installed')
class RealNeuralTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        torch.set_num_threads(1)
        from zara_stock_expert.neural_torch import train
        cls.options = config({'epochs': 5, 'folds': 2, 'lookback': 8})
        cls.artifacts = {name: train(snapshot(), dict(cls.options, architecture=name)) for name in ('mlp', 'tcn')}

    def test_both_networks_really_train_and_report_baselines(self):
        for name, artifact in self.artifacts.items():
            with self.subTest(name=name):
                self.assertEqual(artifact['config']['architecture'], name)
                self.assertGreater(artifact['parameter_count'], 0)
                self.assertTrue(artifact['weights'])
                self.assertEqual(len(artifact['evaluation']['folds']), 2)
                self.assertIn('zero_return_mae', artifact['evaluation']['aggregate'])
                self.assertIn('ridge_mae', artifact['evaluation']['aggregate'])
                self.assertFalse(artifact['execution_eligible'])
                self.assertFalse(artifact['evaluation']['point_in_time_market_backtest'])
                json.dumps(artifact, allow_nan=False)

    def test_train_only_scaler_not_changed_by_test_tail(self):
        from zara_stock_expert.neural_torch import train
        changed = snapshot()
        changed['records'][-1]['close'] = '110'
        second = train(changed, self.options)
        first = self.artifacts['tcn']
        self.assertEqual(first['evaluation']['folds'][0]['scaler'], second['evaluation']['folds'][0]['scaler'])
        self.assertEqual(first['evaluation']['folds'][0]['weights_sha256'], second['evaluation']['folds'][0]['weights_sha256'])

    def test_forecast_json_roundtrip_sorted_intervals_and_no_money_fields(self):
        from zara_stock_expert.neural_torch import forecast
        for artifact in self.artifacts.values():
            result = forecast(json.loads(json.dumps(artifact)), snapshot())
            q = result['log_return_quantiles']
            self.assertLessEqual(q[0], q[1])
            self.assertLessEqual(q[1], q[2])
            self.assertFalse(result['execution_eligible'])
            self.assertFalse(result['coverage_guaranteed'])
            self.assertNotIn('quantity', result)
            self.assertNotIn('cash', result)
            self.assertTrue(all(math.isfinite(v) for v in q))

    def test_forecast_rejects_wrong_series_and_backward_data(self):
        from zara_stock_expert.neural_torch import forecast
        for change in ({'source': 'wrong'}, {'currency': 'EUR'}, {'adjustment': 'total_return'},
                       {'known_at': '2000-01-01T00:00:00+00:00'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                forecast(self.artifacts['mlp'], dict(snapshot(), **change))

    def test_weights_and_architecture_tampering_are_rejected(self):
        from zara_stock_expert.neural_torch import forecast
        changed = copy.deepcopy(self.artifacts['mlp'])
        changed['weights']['surprise'] = [1.0]
        with self.assertRaises(ValueError):
            forecast(changed, snapshot())
        changed = copy.deepcopy(self.artifacts['mlp'])
        changed['config']['lookback'] = 4096
        with self.assertRaises(ValueError):
            forecast(changed, snapshot())

    def test_resealed_malformed_artifacts_are_rejected_before_persistence(self):
        from zara_stock_expert.neural import seal, validate_artifact
        for modify in (
            lambda a: a['weights']['body.0.weight'][0].__setitem__(0, True),
            lambda a: a['weights']['body.0.weight'].__setitem__(0, [1.0]),
            lambda a: a['weights'].update(surprise=[1.0]),
            lambda a: a.update(parameter_count=1),
            lambda a: a.update(dataset_sha256='bad'),
            lambda a: a.update(evidence_ids=['same', 'same']),
            lambda a: a.update(data_last_at='2099-01-01T00:00:00+00:00'),
            lambda a: a['evaluation'].update(point_in_time_market_backtest=True),
        ):
            artifact = copy.deepcopy(self.artifacts['mlp'])
            artifact.pop('model_id')
            modify(artifact)
            with self.subTest(artifact=str(artifact)[:100]), self.assertRaises(ValueError):
                validate_artifact(seal(artifact))

    def test_forecast_cannot_store_malformed_quantiles_or_execution_authority(self):
        from zara_stock_expert.neural_torch import forecast
        result = forecast(self.artifacts['mlp'], snapshot())
        with tempfile.TemporaryDirectory() as root:
            expert = StockExpert(Path(root) / 'private' / 'stock.db', 'test', clock=lambda: NOW)
            try:
                store = NeuralStore(expert)
                store.save_model(self.artifacts['mlp'])
                for change in ({'execution_eligible': True}, {'coverage_guaranteed': True},
                               {'log_return_quantiles': [1, 0, -1]}, {'quantity': 100},
                               {'architecture': 'unknown'}, {'dataset_sha256': 'bad'}):
                    with self.subTest(change=change), self.assertRaises(ValueError):
                        store.save_forecast(dict(result, **change))
            finally:
                expert.close()

    def test_tcn_is_causal(self):
        import torch
        from zara_stock_expert.neural_torch import CausalFeatures
        torch.manual_seed(7)
        network = CausalFeatures().eval()
        before = torch.randn(1, 1, 24)
        after = before.clone()
        after[:, :, 13:] += 100
        self.assertTrue(torch.equal(network(before)[:, :, :13], network(after)[:, :, :13]))

    def test_models_persist_across_restart_and_reject_updates(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'private' / 'stock.db'
            expert = StockExpert(path, 'test', clock=lambda: NOW)
            store = NeuralStore(expert)
            card = store.save_model(self.artifacts['mlp'])
            self.assertNotIn('weights', card)
            self.assertEqual(card, store.save_model(self.artifacts['mlp']))
            with self.assertRaises(sqlite3.IntegrityError):
                expert.db.execute('UPDATE neural_models SET body=body')
            expert.close()
            expert = StockExpert(path, 'test', clock=lambda: NOW)
            try:
                store = NeuralStore(expert)
                self.assertEqual(store.load_model(card['model_id']), self.artifacts['mlp'])
                self.assertEqual(len(store.models('XNAS:EXAMPLE')['models']), 1)
            finally:
                expert.close()

    def test_real_subprocess_train_and_forecast(self):
        from zara_stock_expert.neural_runner import NeuralRunner
        runner = NeuralRunner(timeout_seconds=60)
        try:
            artifact = runner.run('train', {'snapshot': snapshot(), 'options': self.options})
            result = runner.run('forecast', {'artifact': artifact, 'snapshot': snapshot()})
            self.assertEqual(result['architecture'], 'tcn')
            self.assertEqual(artifact['dtype'], 'float32')
        finally:
            runner.stop()
        with self.assertRaises(RuntimeError):
            runner.run('train', {})


class NeuralRunnerBoundaryTest(unittest.TestCase):
    def test_unknown_operation_oversized_input_and_busy_are_rejected(self):
        from zara_stock_expert.neural_runner import NeuralRunner
        runner = NeuralRunner()
        with self.assertRaises(ValueError):
            runner.run('execute_order', {})
        with self.assertRaises(ValueError):
            runner.run('train', {'huge': 'x' * 1048576})
        runner._gate.acquire()
        try:
            with self.assertRaisesRegex(RuntimeError, 'busy'):
                runner.run('train', {})
        finally:
            runner._gate.release()
            runner.stop()

    def test_real_deadline_kills_child_and_releases_slot(self):
        from zara_stock_expert.neural_runner import NeuralRunner
        runner = NeuralRunner()
        runner.timeout = 0.05
        original = subprocess.Popen
        children = []
        def sleeping_worker(command, **kwargs):
            child = original([sys.executable, '-c', 'import time; time.sleep(10)'], **kwargs)
            children.append(child)
            return child
        try:
            with patch('zara_stock_expert.neural_runner.subprocess.Popen', side_effect=sleeping_worker):
                with self.assertRaises(TimeoutError):
                    runner.run('train', {})
            self.assertIsNotNone(children[0].poll())
            self.assertFalse(runner._gate.locked())
        finally:
            runner.stop()

    def test_stop_kills_active_child_and_does_not_forward_api_credentials(self):
        from zara_stock_expert.neural_runner import NeuralRunner
        runner = NeuralRunner()
        original = subprocess.Popen
        ready = threading.Event()
        children, environments, errors = [], [], []
        def sleeping_worker(command, **kwargs):
            environments.append(kwargs['env'])
            child = original([sys.executable, '-c', 'import time; time.sleep(10)'], **kwargs)
            children.append(child)
            ready.set()
            return child
        def run():
            try:
                runner.run('train', {})
            except RuntimeError as error:
                errors.append(error)
        with patch.dict(os.environ, {'ALPHAVANTAGE_API_KEY': 'must-not-reach-child'}), \
                patch('zara_stock_expert.neural_runner.subprocess.Popen', side_effect=sleeping_worker):
            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(ready.wait(3))
            runner.stop()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertIsNotNone(children[0].poll())
        self.assertEqual(len(errors), 1)
        self.assertNotIn('ALPHAVANTAGE_API_KEY', environments[0])
        self.assertEqual(environments[0]['OMP_NUM_THREADS'], '1')


class NeuralServiceBoundaryTest(unittest.TestCase):
    def test_disabled_by_default_without_torch_import_or_hidden_write_tools(self):
        service = StockService()
        self.assertFalse(json.loads(service.status())['neural_enabled'])
        with self.assertRaises(RuntimeError):
            service.neural_train('XNAS:EXAMPLE', 'synthetic')
        service.stop()

    @unittest.skipUnless(HAS_TORCH or REQUIRE, 'optional PyTorch is not installed')
    def test_service_end_to_end_persists_model_forecast_and_keeps_money_exact(self):
        with tempfile.TemporaryDirectory() as root:
            service = StockService()
            worker_list = []
            def start_worker(name, target):
                worker = TestWorker(target)
                worker_list.append(worker)
                return worker
            runtime = SimpleNamespace(configuration={'database': str(Path(root) / 'private' / 'stock.db'),
                'namespace': 'test', 'neural': {'enabled': True, 'timeout_seconds': 60}},
                start_worker=start_worker)
            service.start(runtime)
            try:
                for observation in bars(now=datetime.now(timezone.utc)):
                    service.ingest_bar(observation)
                card = json.loads(service.neural_train('XNAS:EXAMPLE', 'synthetic', epochs=3, folds=2, lookback=8))
                result = json.loads(service.neural_forecast(card['model_id']))
                self.assertFalse(result['payload']['execution_eligible'])
                self.assertEqual(result['provenance'], 'model_forecast')
                from test_stock_expert import size
                assessment = json.loads(service.evaluate('XNAS:EXAMPLE', json.dumps(size())))
                self.assertEqual(assessment['decision'], 'blocked')
                self.assertEqual(len(json.loads(service.neural_models('XNAS:EXAMPLE'))['models']), 1)
                money = json.loads(service.money('add', '{"left":{"amount":"0.1","currency":"USD"},"right":{"amount":"0.2","currency":"USD"}}'))
                self.assertEqual(money['amount'], '0.30')
            finally:
                service.stop()
            self.assertTrue(all(not worker.is_alive for worker in worker_list))
