from __future__ import annotations

import json
import queue
import threading
from collections.abc import Mapping
from concurrent.futures import Future, TimeoutError
from datetime import datetime, timedelta
from pathlib import Path

from .domain import VERSION, StockExpert, bounded_int, calculate, text
from .neural import MAX_BYTES, config as neural_config, dataset as neural_dataset, folds as neural_folds, validate_artifact

MAX_MESSAGE_BYTES = 16384
MAX_MAILBOX = 64
CALL_TIMEOUT = 5.0


def decode(message: str, max_bytes: int = MAX_MESSAGE_BYTES) -> dict:
    if not isinstance(message, str) or len(message.encode('utf-8')) > max_bytes:
        raise ValueError(f'message exceeds {max_bytes} UTF-8 bytes')
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError('non-finite JSON number')
    result = json.loads(message, object_pairs_hook=unique_pairs, parse_constant=invalid_constant)
    if not isinstance(result, dict):
        raise ValueError('message must contain a JSON object')
    return result


class StockService:
    """A bounded mailbox on Zara's lifecycle-owned worker, with one SQLite owner."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queue = queue.Queue(maxsize=MAX_MAILBOX)
        self._worker = None
        self._accepting = False
        self._used = False
        self._max_age = 60
        self._market = None
        self._prolog_enabled = False
        self._neural = None
        self._neural_rows = 512
        self._neural_epochs = 100
        self._neural_age = 7

    def start(self, runtime) -> None:
        section = runtime.configuration
        if not isinstance(section, Mapping):
            raise ValueError('stock expert configuration must be a mapping')
        if 'plugins' in section:
            if set(section) != {'plugins'} or not isinstance(section['plugins'], Mapping):
                raise ValueError('ambiguous legacy stock expert configuration')
            section = section['plugins'].get('zara-stock-expert', {})
        if not isinstance(section, Mapping):
            raise ValueError('stock expert configuration must be a mapping')
        if not section:
            return
        if set(section) - {'database', 'namespace', 'max_quote_age_seconds', 'market_data', 'prolog_enabled', 'neural'}:
            raise ValueError('unknown stock expert configuration')
        database = section.get('database')
        if not isinstance(database, str) or not database:
            raise ValueError('explicit private database path required')
        namespace = text(section.get('namespace'))
        self._max_age = bounded_int(section.get('max_quote_age_seconds', 60), 1, 3600)
        prolog_enabled = section.get('prolog_enabled', False)
        if type(prolog_enabled) is not bool:
            raise ValueError('prolog_enabled must be boolean')
        neural = section.get('neural', {})
        if not isinstance(neural, Mapping) or set(neural) - {'enabled', 'timeout_seconds', 'history_limit', 'max_epochs', 'max_bar_age_days'}:
            raise ValueError('unknown neural configuration')
        enabled = neural.get('enabled', False)
        if type(enabled) is not bool:
            raise ValueError('neural.enabled must be boolean')
        timeout = bounded_int(neural.get('timeout_seconds', 60), 5, 120)
        self._neural_rows = bounded_int(neural.get('history_limit', 512), 128, 1000)
        self._neural_epochs = bounded_int(neural.get('max_epochs', 100), 1, 200)
        self._neural_age = bounded_int(neural.get('max_bar_age_days', 7), 1, 30)
        market = None
        if 'market_data' in section:
            from .market import AlphaVantageSource
            market = AlphaVantageSource(section['market_data'])
        with self._lock:
            if self._used:
                raise RuntimeError('create a fresh plugin instance to restart the owner')
            self._used = True
            self._market = market
            self._prolog_enabled = prolog_enabled
            if enabled:
                from .neural_runner import NeuralRunner
                self._neural = NeuralRunner(timeout)
        ready = Future()
        self._worker = runtime.start_worker('stock-kb', lambda stop: self._run(stop, ready, Path(database), namespace))
        try:
            ready.result(timeout=CALL_TIMEOUT)
        except BaseException:
            self._worker.request_stop()
            self._worker.join(timeout=CALL_TIMEOUT)
            raise

    def _run(self, stop, ready, database: Path, namespace: str) -> None:
        expert = None
        try:
            expert = StockExpert(database, namespace)
            from .neural_store import NeuralStore
            neural_store = NeuralStore(expert)
            prolog = None
            if self._prolog_enabled:
                from .prolog import StockProlog
                prolog = StockProlog(database, namespace)
            def explain(**arguments):
                if prolog is None:
                    raise RuntimeError('Prolog is disabled; configure prolog_enabled=true')
                return prolog.explain(expert.evaluate(**arguments))
            with self._lock:
                self._accepting = True
            ready.set_result(True)
            methods = {'ingest_quote': expert.ingest_quote, 'report_quote': expert.report_quote,
                       'remember_note': expert.remember_note, 'history': expert.history,
                       'evaluate': expert.evaluate, 'explain': explain,
                       'ingest_bar': neural_store.ingest_bar, 'neural_snapshot': neural_store.snapshot,
                       'save_neural_model': neural_store.save_model, 'load_neural_model': neural_store.load_model,
                       'neural_models': neural_store.models, 'save_neural_forecast': neural_store.save_forecast}
            while not stop.is_set():
                try:
                    operation, arguments, reply = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    if not reply.set_running_or_notify_cancel():
                        continue
                    if stop.is_set():
                        raise RuntimeError('stock expert stopped before execution')
                    reply.set_result(methods[operation](**arguments))
                except Exception as error:
                    if not reply.done():
                        reply.set_exception(error)
                finally:
                    self._queue.task_done()
        except BaseException as error:
            if not ready.done():
                ready.set_exception(error)
            raise
        finally:
            with self._lock:
                self._accepting = False
                while True:
                    try:
                        _, _, reply = self._queue.get_nowait()
                    except queue.Empty:
                        break
                    if not reply.done():
                        reply.set_exception(RuntimeError('stock expert stopped'))
                    self._queue.task_done()
            if expert is not None:
                expert.close()

    def stop(self) -> None:
        with self._lock:
            self._accepting = False
        if self._neural is not None:
            self._neural.stop()
        if self._worker is not None:
            self._worker.request_stop()
            self._worker.join(timeout=CALL_TIMEOUT)
            if self._worker.is_alive:
                raise RuntimeError('stock expert owner has not stopped')

    def _ask(self, operation: str, arguments: dict) -> dict:
        if operation not in {'ingest_quote', 'report_quote', 'remember_note', 'history', 'evaluate', 'explain',
                             'ingest_bar', 'neural_snapshot', 'save_neural_model', 'load_neural_model',
                             'neural_models', 'save_neural_forecast'}:
            raise ValueError('unknown mailbox operation')
        arguments = decode(json.dumps(arguments, allow_nan=False),
                           MAX_BYTES + 64 if operation == 'save_neural_model' else MAX_MESSAGE_BYTES)
        reply = Future()
        with self._lock:
            if not self._accepting:
                raise RuntimeError('stock expert is not configured or is stopped')
            try:
                self._queue.put_nowait((operation, arguments, reply))
            except queue.Full as error:
                raise RuntimeError('stock expert mailbox is full') from error
        try:
            return reply.result(timeout=CALL_TIMEOUT)
        except TimeoutError as error:
            cancelled = reply.cancel()
            status = 'cancelled before execution' if cancelled else 'outcome unknown; retry the same event_id'
            raise TimeoutError(f'stock expert timeout: {status}') from error

    def status(self) -> str:
        with self._lock:
            configured = self._accepting
        return json.dumps({'configured': configured, 'version': VERSION, 'live_execution': False,
                           'neural_enabled': configured and self._neural is not None,
                           'neural_architectures': ['mlp', 'tcn'], 'neural_precision': 'float32_cpu',
                           'neural_execution_eligible': False,
                           'market_data_configured': configured and self._market is not None,
                           'prolog_registered': configured and self._prolog_enabled,
                           'mailbox_capacity': MAX_MAILBOX, 'max_quote_age_seconds': self._max_age})

    def ingest_quote(self, observation: dict) -> dict:
        """Only trusted stock API adapter code calls this; never in tools()."""
        return self._ask('ingest_quote', {'observation': observation})

    def report_quote(self, observation_json: str) -> str:
        return json.dumps(self._ask('report_quote', {'observation': decode(observation_json)}), sort_keys=True)

    def remember_note(self, event_id: str, instrument: str, note: str, source: str = 'llm') -> str:
        return json.dumps(self._ask('remember_note', dict(event_id=event_id, instrument=instrument,
                                                         note=note, source=source)), sort_keys=True)

    def history(self, instrument: str, effective_at: str | None = None,
                known_at: str | None = None, limit: int = 100, revisions: bool = False) -> str:
        return json.dumps(self._ask('history', dict(instrument=instrument, effective_at=effective_at,
                                                   known_at=known_at, limit=limit, revisions=revisions)), sort_keys=True)

    def money(self, operation: str, arguments_json: str) -> str:
        return json.dumps(calculate(operation, decode(arguments_json)), sort_keys=True)

    def evaluate(self, instrument: str, sizing_json: str, mode: str = 'paper') -> str:
        return json.dumps(self._ask('evaluate', dict(instrument=instrument, sizing=decode(sizing_json),
                                                    mode=mode, max_age_seconds=self._max_age)), sort_keys=True)

    def fetch_quote(self, instrument: str) -> str:
        with self._lock:
            if not self._accepting or self._market is None:
                raise RuntimeError('market data is not configured or service is stopped')
            source = self._market
        observation = source.fetch(instrument)
        return json.dumps(self.ingest_quote(observation), sort_keys=True)

    def explain(self, instrument: str, sizing_json: str, mode: str = 'paper') -> str:
        return json.dumps(self._ask('explain', dict(instrument=instrument, sizing=decode(sizing_json),
                                                   mode=mode, max_age_seconds=self._max_age)), sort_keys=True)

    def ingest_bar(self, observation: dict) -> dict:
        """Trusted stock API adapter only; not an LLM-facing observation authority."""
        return self._ask('ingest_bar', {'observation': observation})

    def _neural_runner(self):
        with self._lock:
            if not self._accepting or self._neural is None:
                raise RuntimeError('neural research is disabled or service is stopped')
            return self._neural

    def neural_train(self, instrument: str, source: str, architecture: str = 'tcn',
                     lookback: int = 16, horizon: int = 1, epochs: int = 40,
                     folds: int = 3, seed: int = 17) -> str:
        runner = self._neural_runner()
        options = neural_config(dict(architecture=architecture, lookback=lookback, horizon=horizon,
                                      epochs=epochs, folds=folds, seed=seed))
        if epochs > self._neural_epochs:
            raise ValueError('training epochs exceed operator cap')
        snapshot = self._ask('neural_snapshot', dict(instrument=instrument, source=source, limit=self._neural_rows))
        data = neural_dataset(snapshot, options)
        neural_folds(len(data['y']), options)
        artifact = validate_artifact(runner.run('train', dict(snapshot=snapshot, options=options)))
        return json.dumps(self._ask('save_neural_model', {'artifact': artifact}), sort_keys=True, allow_nan=False)

    def neural_forecast(self, model_id: str) -> str:
        runner = self._neural_runner()
        artifact = self._ask('load_neural_model', {'model_id': model_id})
        snapshot = self._ask('neural_snapshot', dict(instrument=artifact['instrument'], source=artifact['source'],
                                                    limit=artifact['config']['lookback'] + 1))
        if not snapshot['records']:
            raise ValueError('missing forecast bars')
        age = datetime.fromisoformat(snapshot['known_at']) - datetime.fromisoformat(snapshot['records'][-1]['effective_at'])
        if age > timedelta(days=self._neural_age):
            raise ValueError('stale daily close; no current neural forecast issued')
        result = runner.run('forecast', dict(artifact=artifact, snapshot=snapshot))
        return json.dumps(self._ask('save_neural_forecast', {'forecast': result}), sort_keys=True, allow_nan=False)

    def neural_models(self, instrument: str, limit: int = 20) -> str:
        return json.dumps(self._ask('neural_models', dict(instrument=instrument, limit=limit)), sort_keys=True)
