from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
from datetime import date, datetime, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Callable

VERSION = '0.1.0'
NUMBER = re.compile(r'-?(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,12})?\Z')
IDENTIFIER = re.compile(r'[A-Za-z0-9_.:/@-]{1,96}\Z')
INSTRUMENT = re.compile(r'[A-Z0-9]{2,10}:[A-Z0-9._-]{1,32}\Z')
CURRENCY = re.compile(r'[A-Z]{3}\Z')


def number(value: object, *, positive: bool = False, signed: bool = False) -> Fraction:
    if not isinstance(value, str) or not NUMBER.fullmatch(value):
        raise ValueError('number must be a bounded plain decimal string, never a float')
    result = Fraction(Decimal(value))
    if (positive and result <= 0) or (not signed and result < 0):
        raise ValueError('number is outside the permitted range')
    return result


def text(value: object, pattern: re.Pattern = IDENTIFIER) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError('invalid or oversized identifier')
    return value


def shape(values: object, required: set[str], optional: set[str] = frozenset()) -> dict:
    if not isinstance(values, dict) or not required <= values.keys() or values.keys() - required - optional:
        raise ValueError('missing or unknown fields')
    return values


def bounded_int(value: object, lower: int, upper: int) -> int:
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError('integer outside permitted bounds')
    return value


def fixed(value: Fraction, places: int = 2, rounding: str = 'half_even') -> str:
    bounded_int(places, 0, 12)
    scale = 10 ** places
    units, remainder = divmod(value.numerator * scale, value.denominator)
    if rounding == 'half_even':
        units += int(2 * remainder > value.denominator or
                     (2 * remainder == value.denominator and units % 2 != 0))
    elif rounding == 'ceiling':
        units += int(remainder != 0)
    elif rounding == 'exact':
        if remainder:
            raise ValueError('inexact decimal representation')
    elif rounding != 'floor':
        raise ValueError('unsupported rounding')
    sign = '-' if units < 0 else ''
    whole, fraction = divmod(abs(units), scale)
    return f'{sign}{whole}.{fraction:0{places}d}' if places else f'{sign}{whole}'


def plain(value: Fraction) -> str:
    return fixed(value, 12, 'exact').rstrip('0').rstrip('.')


def floor_step(value: Fraction, step: Fraction) -> Fraction:
    return max(0, value // step) * step


def calculate(operation: str, values: dict) -> dict:
    if operation == 'add':
        shape(values, {'left', 'right'}, {'places'})
        for side in ('left', 'right'):
            shape(values[side], {'amount', 'currency'})
            text(values[side]['currency'], CURRENCY)
        if values['left']['currency'] != values['right']['currency']:
            raise ValueError('currency mismatch; an explicit sourced FX conversion is required')
        amount = number(values['left']['amount'], signed=True) + number(values['right']['amount'], signed=True)
        return {'amount': fixed(amount, values.get('places', 2)),
                'currency': values['left']['currency'], 'rounding': 'half_even'}

    common = {'currency', 'entry', 'entry_fee', 'exit_fee'}
    if operation == 'position_size':
        required = common | {'equity', 'cash', 'stop', 'risk_fraction', 'max_position_fraction',
                             'quantity_step', 'price_tick', 'slippage_per_share', 'existing_exposure'}
    elif operation == 'pnl':
        required = common | {'quantity', 'exit'}
    elif operation == 'break_even':
        required = common | {'quantity', 'price_tick'}
    else:
        raise ValueError('unsupported money operation')
    shape(values, required, {'places'})
    currency = text(values['currency'], CURRENCY)
    places = bounded_int(values.get('places', 2), 0, 8)
    numbers = {key: number(value) for key, value in values.items() if key not in ('currency', 'places')}
    entry, buy_fee, sell_fee = (numbers[key] for key in ('entry', 'entry_fee', 'exit_fee'))
    if entry <= 0:
        raise ValueError('entry must be positive')
    output = {'currency': currency, 'places': places}

    if operation == 'position_size':
        equity, stop = numbers['equity'], numbers['stop']
        risk, cap = numbers['risk_fraction'], numbers['max_position_fraction']
        step, tick = numbers['quantity_step'], numbers['price_tick']
        if equity <= 0 or not 0 < risk <= 1 or not 0 < cap <= 1 or not 0 <= stop < entry or step <= 0 or tick <= 0:
            raise ValueError('invalid long-only risk, price, equity or step')
        if (entry / tick).denominator != 1 or (stop / tick).denominator != 1:
            raise ValueError('entry and stop must align with the explicit price tick')
        budget = equity * risk
        per_share_loss = entry - stop + numbers['slippage_per_share']
        by_risk = (budget - buy_fee - sell_fee) / per_share_loss
        by_cash = (numbers['cash'] - buy_fee) / entry
        by_exposure = (equity * cap - numbers['existing_exposure']) / entry
        quantity = floor_step(min(by_risk, by_cash, by_exposure), step)
        notional = quantity * entry
        loss = quantity * per_share_loss + buy_fee + sell_fee if quantity else Fraction(0)
        cost = notional + buy_fee if quantity else Fraction(0)
        assert quantity >= 0 and (not quantity or (loss <= budget and cost <= numbers['cash']))
        output.update(quantity=plain(quantity), notional=fixed(notional, places, 'ceiling'),
                      cash_required=fixed(cost, places, 'ceiling'),
                      estimated_stop_loss=fixed(loss, places, 'ceiling'),
                      risk_budget=fixed(budget, places, 'floor'),
                      rounding='quantity_floor; costs_ceiling; budget_floor',
                      loss_bound_guaranteed=False)
        return output

    quantity = numbers['quantity']
    if quantity <= 0:
        raise ValueError('quantity must be positive')
    basis = quantity * entry + buy_fee
    if operation == 'pnl':
        proceeds = quantity * numbers['exit'] - sell_fee
        output.update(cost_basis=fixed(basis, places), proceeds=fixed(proceeds, places),
                      gross_pnl=fixed(quantity * (numbers['exit'] - entry), places),
                      net_pnl=fixed(proceeds - basis, places), rounding='half_even')
    else:
        tick = numbers['price_tick']
        if tick <= 0:
            raise ValueError('price tick must be positive')
        ticks = (basis + sell_fee) / quantity / tick
        tick_count = -(-ticks.numerator // ticks.denominator)
        output.update(price=plain(tick_count * tick), rounding='ceiling_to_price_tick')
    return output


def timestamp(value: str) -> str:
    if not isinstance(value, str) or not 20 <= len(value) <= 40:
        raise ValueError('timestamp must include a timezone')
    try:
        instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise ValueError('invalid timestamp') from error
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError('timestamp must include a timezone')
    return instant.astimezone(timezone.utc).isoformat(timespec='microseconds')


class StockExpert:
    """Single-owner connection. Provider ingestion is not an LLM tool authority."""

    def __init__(self, path: Path, namespace: str,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.namespace = text(namespace)
        self.clock = clock
        path = Path(path).expanduser()
        if not path.is_absolute() or Path('/nix/store') in path.parents:
            raise ValueError('database must be an absolute writable state path outside the Nix store')
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.is_symlink() or path.parent.is_symlink() or path.parent.stat().st_mode & 0o077:
            raise ValueError('database requires a private non-symlink directory')
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise ValueError('database must be a private regular file')
        finally:
            os.close(descriptor)
        self.db = sqlite3.connect(path, timeout=2.0)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    namespace TEXT NOT NULL, event_id TEXT NOT NULL,
                    kind TEXT NOT NULL, instrument TEXT NOT NULL,
                    effective_at TEXT NOT NULL, recorded_at TEXT NOT NULL,
                    provenance TEXT NOT NULL, source TEXT NOT NULL,
                    supersedes TEXT, body TEXT NOT NULL,
                    UNIQUE(namespace, event_id), UNIQUE(namespace, supersedes)
                );
                CREATE INDEX IF NOT EXISTS events_lookup
                ON events(namespace, instrument, effective_at, recorded_at);
                CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
                BEGIN SELECT RAISE(ABORT, 'append-only events'); END;
                CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
                BEGIN SELECT RAISE(ABORT, 'append-only events'); END;
            ''')
        except BaseException:
            self.db.close()
            raise

    def close(self) -> None:
        self.db.close()

    def _now(self) -> str:
        return timestamp(self.clock().isoformat())

    def ingest_quote(self, observation: dict) -> dict:
        """Trusted in-process stock API adapter boundary; not registered as an LLM tool."""
        return self._quote(observation, 'provider_adapter')

    def report_quote(self, observation: dict) -> dict:
        """Model-mediated reports are retained but never promoted to verified provider data."""
        return self._quote(observation, 'unverified_report')

    def _quote(self, observation: dict, provenance: str) -> dict:
        shape(observation, {'event_id', 'instrument', 'source', 'effective_at', 'price',
                            'currency', 'adjustment', 'feed', 'price_kind'},
              {'supersedes', 'timestamp_precision', 'trading_day'})
        number(observation['price'], positive=True)
        text(observation['currency'], CURRENCY)
        if observation['adjustment'] not in ('raw', 'split', 'total_return', 'unknown'):
            raise ValueError('unknown price adjustment')
        if observation['feed'] not in ('realtime', 'delayed', 'historical'):
            raise ValueError('unknown market feed')
        if observation['price_kind'] not in ('bid', 'ask', 'last'):
            raise ValueError('unknown quote kind')
        payload = {key: observation[key] for key in ('price', 'currency', 'adjustment', 'feed', 'price_kind')}
        precision = observation.get('timestamp_precision', 'instant')
        if precision not in ('instant', 'day'):
            raise ValueError('unknown quote timestamp precision')
        if precision == 'day':
            day = observation.get('trading_day')
            if (not isinstance(day, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', day)
                    or date.fromisoformat(day).isoformat() != day
                    or timestamp(observation['effective_at']) != timestamp(day + 'T00:00:00+00:00')
                    or observation['feed'] != 'historical'):
                raise ValueError('day-precision quote must use a historical UTC date index')
            payload.update(timestamp_precision='day', trading_day=day)
        elif 'trading_day' in observation:
            raise ValueError('trading_day requires explicit day precision')
        return self._record(event_id=observation['event_id'], instrument=observation['instrument'],
                            source=observation['source'], effective_at=observation['effective_at'],
                            kind='quote', provenance=provenance, payload=payload,
                            supersedes=observation.get('supersedes'))

    def remember_note(self, event_id: str, instrument: str, note: str, source: str) -> dict:
        if not isinstance(note, str) or not 1 <= len(note.encode('utf-8')) <= 4096:
            raise ValueError('note must contain 1 to 4096 UTF-8 bytes')
        return self._record(event_id=event_id, instrument=instrument, source=source,
                            effective_at=self._now(), kind='note', provenance='model_note',
                            payload={'text': note}, supersedes=None)

    def _record(self, *, event_id: str, instrument: str, source: str, effective_at: str,
                kind: str, provenance: str, payload: dict, supersedes: str | None) -> dict:
        event_id, instrument, source = text(event_id), text(instrument, INSTRUMENT), text(source)
        effective_at, received = timestamp(effective_at), self._now()
        if effective_at > received:
            raise ValueError('future-dated market evidence is not accepted')
        if supersedes is not None:
            text(supersedes)
        body = json.dumps(dict(event_id=event_id, instrument=instrument, source=source,
                               effective_at=effective_at, kind=kind, provenance=provenance,
                               payload=payload, supersedes=supersedes), sort_keys=True, separators=(',', ':'))
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            existing = self.db.execute('SELECT * FROM events WHERE namespace=? AND event_id=?',
                                       (self.namespace, event_id)).fetchone()
            if existing:
                old, new = json.loads(existing['body']), json.loads(body)
                if kind == 'note' and old['kind'] == 'note':
                    old.pop('effective_at')
                    new.pop('effective_at')
                if old != new:
                    raise ValueError('idempotency conflict: use a new event_id and explicit supersedes')
                return self._decode(existing)
            if supersedes is not None:
                parent = self.db.execute('SELECT * FROM events WHERE namespace=? AND event_id=?',
                                         (self.namespace, supersedes)).fetchone()
                if not parent or any(parent[key] != value for key, value in
                                     (('instrument', instrument), ('source', source), ('effective_at', effective_at),
                                      ('kind', kind), ('provenance', provenance))):
                    raise ValueError('correction must preserve instrument, source, kind and provenance')
            try:
                cursor = self.db.execute('''INSERT INTO events
                    (namespace,event_id,kind,instrument,effective_at,recorded_at,provenance,source,supersedes,body)
                    VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (self.namespace, event_id, kind, instrument, effective_at, received,
                     provenance, source, supersedes, body))
            except sqlite3.IntegrityError as error:
                raise ValueError('correction lineage already has a successor') from error
            row = self.db.execute('SELECT * FROM events WHERE sequence=?', (cursor.lastrowid,)).fetchone()
            assert row is not None
            return self._decode(row)

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict:
        result = json.loads(row['body'])
        result.update(recorded_at=row['recorded_at'], sequence=row['sequence'])
        return result

    def history(self, instrument: str, *, effective_at: str | None = None,
                known_at: str | None = None, limit: int = 100,
                revisions: bool = False, kind: str | None = None) -> dict:
        text(instrument, INSTRUMENT)
        bounded_int(limit, 1, 1000)
        if type(revisions) is not bool or kind not in (None, 'quote', 'note'):
            raise ValueError('invalid history options')
        effective, known = timestamp(effective_at) if effective_at else self._now(), timestamp(known_at) if known_at else self._now()
        sql = '''SELECT e.* FROM events e WHERE e.namespace=? AND e.instrument=?
                 AND e.effective_at<=? AND e.recorded_at<=?'''
        params = [self.namespace, instrument, effective, known]
        if kind is not None:
            sql += ' AND e.kind=?'
            params.append(kind)
        if not revisions:
            sql += ''' AND NOT EXISTS (SELECT 1 FROM events r WHERE r.namespace=e.namespace
                       AND r.supersedes=e.event_id AND r.effective_at<=? AND r.recorded_at<=?)'''
            params.extend([effective, known])
        sql += ' ORDER BY e.effective_at DESC, e.sequence DESC LIMIT ?'
        params.append(limit + 1)
        rows = self.db.execute(sql, params).fetchall()
        return {'records': [self._decode(row) for row in rows[:limit]],
                'truncated': len(rows) > limit, 'effective_at': effective, 'known_at': known}

    def evaluate(self, instrument: str, sizing: dict, *, mode: str = 'paper',
                 max_age_seconds: int = 60) -> dict:
        bounded_int(max_age_seconds, 1, 3600)
        if mode not in ('paper', 'live'):
            raise ValueError('unknown trading mode')
        result = calculate('position_size', sizing)
        now = self._now()
        records = self.history(instrument, known_at=now, effective_at=now, limit=1, kind='quote')['records']
        blockers = []
        evidence = []
        if mode != 'paper':
            blockers.append('live_execution_unavailable')
        if not records:
            blockers.append('missing_provider_quote')
        else:
            record = records[0]
            evidence.append(record['event_id'])
            payload = record['payload']
            if record['provenance'] != 'provider_adapter':
                blockers.append('unverified_quote')
            age = datetime.fromisoformat(now) - datetime.fromisoformat(record['effective_at'])
            if age.total_seconds() > max_age_seconds:
                blockers.append('stale_quote')
            if payload['feed'] != 'realtime':
                blockers.append('not_realtime')
            if payload.get('timestamp_precision', 'instant') != 'instant':
                blockers.append('imprecise_quote_time')
            if payload['adjustment'] == 'unknown':
                blockers.append('unknown_price_adjustment')
            elif payload['adjustment'] != 'raw':
                blockers.append('adjusted_price')
            if payload['currency'] != sizing['currency']:
                blockers.append('currency_mismatch')
            if number(payload['price']) != number(sizing['entry']):
                blockers.append('entry_price_mismatch')
        if number(result['quantity']) == 0:
            blockers.append('zero_affordable_quantity')
        digest = hashlib.sha256(json.dumps(sizing, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        return {'decision': 'blocked' if blockers else 'paper_candidate', 'blockers': blockers,
                'executable': False, 'mode': mode, 'instrument': instrument, 'sizing': result,
                'evidence_ids': evidence, 'evaluated_at': now, 'policy_version': VERSION,
                'input_sha256': digest, 'strategy_signal': 'not_evaluated'}
