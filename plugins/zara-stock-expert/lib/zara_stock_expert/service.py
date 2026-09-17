from __future__ import annotations

import json
import queue
import threading
from collections.abc import Mapping
from concurrent.futures import Future, TimeoutError
from pathlib import Path

from .domain import VERSION, StockExpert, bounded_int, calculate, text

MAX_MESSAGE_BYTES = 16384
MAX_MAILBOX = 64
CALL_TIMEOUT = 5.0


def decode(message: str) -> dict:
    if not isinstance(message, str) or len(message.encode('utf-8')) > MAX_MESSAGE_BYTES:
        raise ValueError('message exceeds 16384 UTF-8 bytes')
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

    def start(self, runtime) -> None:
        plugins = runtime.configuration.get('plugins', {})
        if not isinstance(plugins, Mapping):
            raise ValueError('plugins must be a mapping')
        section = plugins.get('zara-stock-expert')
        if section is None:
            return
        if not isinstance(section, Mapping) or set(section) - {'database', 'namespace', 'max_quote_age_seconds'}:
            raise ValueError('unknown stock expert configuration')
        database = section.get('database')
        if not isinstance(database, str) or not database:
            raise ValueError('explicit private database path required')
        namespace = text(section.get('namespace'))
        self._max_age = bounded_int(section.get('max_quote_age_seconds', 60), 1, 3600)
        with self._lock:
            if self._used:
                raise RuntimeError('create a fresh plugin instance to restart the owner')
            self._used = True
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
            with self._lock:
                self._accepting = True
            ready.set_result(True)
            methods = {'ingest_quote': expert.ingest_quote, 'report_quote': expert.report_quote,
                       'remember_note': expert.remember_note, 'history': expert.history,
                       'evaluate': expert.evaluate}
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
        if self._worker is not None:
            self._worker.request_stop()
            self._worker.join(timeout=CALL_TIMEOUT)
            if self._worker.is_alive:
                raise RuntimeError('stock expert owner has not stopped')

    def _ask(self, operation: str, arguments: dict) -> dict:
        if operation not in {'ingest_quote', 'report_quote', 'remember_note', 'history', 'evaluate'}:
            raise ValueError('unknown mailbox operation')
        arguments = decode(json.dumps(arguments, allow_nan=False))
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
