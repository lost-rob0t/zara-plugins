from __future__ import annotations

import json
import math
import re

from .domain import CURRENCY, INSTRUMENT, bounded_int, number, shape, text, timestamp
from .neural import canonical, fingerprint, validate_artifact


class NeuralStore:
    """All methods run on the existing single-owner SQLite mailbox."""

    def __init__(self, expert) -> None:
        self.expert = expert
        expert.db.executescript('''
            CREATE TABLE IF NOT EXISTS neural_models (
                namespace TEXT NOT NULL, model_id TEXT NOT NULL, instrument TEXT NOT NULL,
                created_at TEXT NOT NULL, body TEXT NOT NULL,
                PRIMARY KEY(namespace, model_id)
            );
            CREATE TRIGGER IF NOT EXISTS neural_models_no_update BEFORE UPDATE ON neural_models
            BEGIN SELECT RAISE(ABORT, 'append-only neural models'); END;
            CREATE TRIGGER IF NOT EXISTS neural_models_no_delete BEFORE DELETE ON neural_models
            BEGIN SELECT RAISE(ABORT, 'append-only neural models'); END;
        ''')

    def ingest_bar(self, observation: dict) -> dict:
        shape(observation, {'event_id', 'instrument', 'source', 'effective_at', 'close', 'currency',
                            'adjustment', 'interval', 'session_index'}, {'supersedes'})
        number(observation['close'], positive=True)
        text(observation['currency'], CURRENCY)
        bounded_int(observation['session_index'], 0, 2147483647)
        if observation['adjustment'] not in ('split', 'total_return') or observation['interval'] != '1d':
            raise ValueError('bar requires an explicitly adjusted daily close and session index')
        payload = {key: observation[key] for key in ('close', 'currency', 'adjustment', 'interval', 'session_index')}
        return self.expert._record(event_id=observation['event_id'], instrument=observation['instrument'],
            source=observation['source'], effective_at=observation['effective_at'], kind='bar',
            provenance='provider_adapter', payload=payload, supersedes=observation.get('supersedes'))

    def snapshot(self, instrument: str, source: str, limit: int = 512, known_at: str | None = None) -> dict:
        text(instrument, INSTRUMENT)
        text(source)
        bounded_int(limit, 2, 1000)
        known = timestamp(known_at) if known_at else self.expert._now()
        if known > self.expert._now():
            raise ValueError('future knowledge cutoff is not accepted')
        rows = self.expert.db.execute('''SELECT e.* FROM events e WHERE
            e.namespace=? AND e.instrument=? AND e.source=? AND e.kind='bar'
            AND e.provenance='provider_adapter' AND e.recorded_at<=? AND e.effective_at<=?
            AND NOT EXISTS (SELECT 1 FROM events r WHERE r.namespace=e.namespace
                AND r.supersedes=e.event_id AND r.recorded_at<=? AND r.effective_at<=?)
            ORDER BY e.effective_at DESC,e.sequence DESC LIMIT ?''',
            (self.expert.namespace, instrument, source, known, known, known, known, limit + 1)).fetchall()
        records = [self.expert._decode(row) for row in reversed(rows[:limit])]
        result = dict(instrument=instrument, source=source, known_at=known,
                      currency=None, adjustment=None, interval='1d', history_truncated=len(rows) > limit, records=[])
        if not records:
            return result
        semantics = ('currency', 'adjustment', 'interval')
        for key in semantics:
            result[key] = records[0]['payload'][key]
        for record in records:
            if any(record['payload'][key] != result[key] for key in semantics):
                raise ValueError('mixed currency, adjustment or interval in neural history')
            result['records'].append(dict(event_id=record['event_id'], effective_at=record['effective_at'],
                recorded_at=record['recorded_at'], close=record['payload']['close'],
                session_index=record['payload']['session_index']))
        return result

    @staticmethod
    def _card(artifact: dict, created_at: str) -> dict:
        return dict({key: value for key, value in artifact.items() if key not in ('weights', 'evidence_ids')},
                    created_at=created_at, evidence_count=len(artifact['evidence_ids']))

    def save_model(self, artifact: dict) -> dict:
        validate_artifact(artifact)
        if timestamp(artifact['known_at']) > self.expert._now():
            raise ValueError('future model knowledge cutoff')
        body = canonical(artifact)
        with self.expert.db:
            self.expert.db.execute('INSERT OR IGNORE INTO neural_models VALUES (?,?,?,?,?)',
                (self.expert.namespace, artifact['model_id'], artifact['instrument'], self.expert._now(), body))
            row = self.expert.db.execute('SELECT * FROM neural_models WHERE namespace=? AND model_id=?',
                (self.expert.namespace, artifact['model_id'])).fetchone()
            if row['body'] != body:
                raise ValueError('model ID conflict')
        return self._card(artifact, row['created_at'])

    def load_model(self, model_id: str) -> dict:
        text(model_id)
        row = self.expert.db.execute('SELECT body FROM neural_models WHERE namespace=? AND model_id=?',
                                    (self.expert.namespace, model_id)).fetchone()
        if row is None:
            raise ValueError('model is not registered in this namespace')
        return validate_artifact(json.loads(row['body']))

    def models(self, instrument: str, limit: int = 20) -> dict:
        text(instrument, INSTRUMENT)
        bounded_int(limit, 1, 100)
        rows = self.expert.db.execute('''SELECT body,created_at FROM neural_models
            WHERE namespace=? AND instrument=? ORDER BY created_at DESC,model_id LIMIT ?''',
            (self.expert.namespace, instrument, limit + 1)).fetchall()
        return dict(models=[self._card(json.loads(row['body']), row['created_at']) for row in rows[:limit]],
                    truncated=len(rows) > limit)

    def save_forecast(self, forecast: dict) -> dict:
        shape(forecast, {'model_id', 'architecture', 'instrument', 'model_dataset_sha256', 'input_sha256',
            'as_of', 'data_last_at', 'horizon_observed_sessions', 'quantile_levels', 'log_return_quantiles',
            'target', 'nominal_interval_coverage', 'coverage_guaranteed', 'execution_eligible',
            'input_out_of_training_range', 'disposition', 'warnings'})
        artifact = self.load_model(forecast['model_id'])
        if (forecast['execution_eligible'] is not False or forecast['coverage_guaranteed'] is not False
                or forecast['instrument'] != artifact['instrument']
                or forecast['architecture'] != artifact['config']['architecture']
                or forecast['model_dataset_sha256'] != artifact['dataset_sha256']
                or forecast['horizon_observed_sessions'] != artifact['config']['horizon']
                or forecast['target'] != 'adjusted_close_log_return'
                or forecast['nominal_interval_coverage'] != 0.8
                or forecast['quantile_levels'] != [0.1, 0.5, 0.9]):
            raise ValueError('invalid forecast semantics or execution authority')
        q = forecast['log_return_quantiles']
        if (not isinstance(q, list) or len(q) != 3
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in q)
                or not q[0] <= q[1] <= q[2]):
            raise ValueError('invalid forecast quantiles')
        drift = forecast['input_out_of_training_range']
        if (type(drift) is not bool or forecast['disposition'] != ('abstain' if drift else 'research_forecast')
                or not isinstance(forecast['input_sha256'], str)
                or not re.fullmatch('[0-9a-f]{64}', forecast['input_sha256'])):
            raise ValueError('invalid forecast provenance or drift metadata')
        if (timestamp(forecast['data_last_at']) < timestamp(artifact['data_last_at'])
                or not timestamp(artifact['known_at']) <= timestamp(forecast['as_of']) <= self.expert._now()
                or timestamp(forecast['data_last_at']) > timestamp(forecast['as_of'])):
            raise ValueError('invalid forecast temporal provenance')
        return self.expert._record(event_id='forecast-' + fingerprint(forecast),
            instrument=artifact['instrument'], source=forecast['model_id'], effective_at=forecast['as_of'],
            kind='forecast', provenance='model_forecast', payload=forecast, supersedes=None)
