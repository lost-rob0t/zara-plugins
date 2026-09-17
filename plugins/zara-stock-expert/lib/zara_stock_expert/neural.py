from __future__ import annotations

import hashlib
import json
import math
import re

from .domain import CURRENCY, INSTRUMENT, bounded_int, number, shape, text, timestamp

SCHEMA = 'stock-neural-v1'
MAX_BYTES = 524288
MAX_ROWS = 1000
DEFAULTS = dict(architecture='tcn', lookback=16, horizon=1, epochs=40, folds=3, seed=17)
QUANTILES = (0.1, 0.5, 0.9)


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def config(values: dict) -> dict:
    shape(values, set(), set(DEFAULTS))
    result = dict(DEFAULTS, **values)
    if result['architecture'] not in ('mlp', 'tcn'):
        raise ValueError('neural architecture must be mlp or tcn')
    for key, low, high in (('lookback', 8, 64), ('horizon', 1, 20), ('epochs', 1, 200),
                           ('folds', 1, 4), ('seed', 0, 2147483647)):
        bounded_int(result[key], low, high)
    return result


def series(snapshot: dict) -> list[float]:
    shape(snapshot, {'instrument', 'source', 'currency', 'adjustment', 'interval',
                     'known_at', 'history_truncated', 'records'})
    text(snapshot['instrument'], INSTRUMENT)
    text(snapshot['source'])
    text(snapshot['currency'], CURRENCY)
    known = timestamp(snapshot['known_at'])
    if snapshot['adjustment'] not in ('split', 'total_return') or snapshot['interval'] != '1d':
        raise ValueError('neural research requires explicitly adjusted daily closes')
    if type(snapshot['history_truncated']) is not bool:
        raise ValueError('invalid truncation metadata')
    rows = snapshot['records']
    if not isinstance(rows, list) or not 2 <= len(rows) <= MAX_ROWS:
        raise ValueError('insufficient or excessive daily close observations')
    prices, seen = [], set()
    previous_time, previous_session = None, None
    for row in rows:
        shape(row, {'event_id', 'effective_at', 'recorded_at', 'close', 'session_index'})
        event_id = text(row['event_id'])
        instant, recorded = timestamp(row['effective_at']), timestamp(row['recorded_at'])
        session = bounded_int(row['session_index'], 0, 2147483647)
        if (event_id in seen or instant > known or recorded > known
                or (previous_time is not None and instant <= previous_time)
                or (previous_session is not None and session != previous_session + 1)):
            raise ValueError('duplicate, future, out-of-order or missing-session observations')
        prices.append(float(number(row['close'], positive=True)))
        seen.add(event_id)
        previous_time, previous_session = instant, session
    return prices


def dataset(snapshot: dict, options: dict) -> dict:
    options = config(options)
    prices = series(snapshot)
    lookback, horizon = options['lookback'], options['horizon']
    if len(prices) <= lookback + horizon:
        raise ValueError('insufficient data for the requested context and horizon')
    returns = [math.log(right / left) for left, right in zip(prices, prices[1:])]
    origins = list(range(lookback, len(prices) - horizon))
    return dict(x=[returns[p - lookback:p] for p in origins],
                y=[math.log(prices[p + horizon] / prices[p]) for p in origins],
                origins=origins, label_ends=[p + horizon for p in origins],
                context=returns[-lookback:])


def partition(end: int, horizon: int, test_size: int = 0) -> dict:
    calibration_end = end - test_size - (horizon if test_size else 0)
    calibration_start = calibration_end - 16
    validation_end = calibration_start - horizon
    validation_start = validation_end - 16
    train_end = validation_start - horizon
    if train_end < 32:
        raise ValueError('insufficient samples for purged train/validation/calibration/test blocks')
    result = dict(train=[0, train_end], validation=[validation_start, validation_end],
                  calibration=[calibration_start, calibration_end])
    if test_size:
        result['test'] = [end - test_size, end]
    return result


def folds(count: int, options: dict) -> list[dict]:
    options = config(options)
    bounded_int(count, 1, MAX_ROWS)
    return [partition(count - (options['folds'] - i - 1) * 16, options['horizon'], 16)
            for i in range(options['folds'])]


def seal(artifact: dict) -> dict:
    return dict(artifact, model_id='nn-' + fingerprint(artifact))


def weight_shapes(options: dict) -> dict:
    if options['architecture'] == 'mlp':
        return {'body.0.weight': (16, options['lookback']), 'body.0.bias': (16,),
                'body.2.weight': (16, 16), 'body.2.bias': (16,),
                'body.4.weight': (3, 16), 'body.4.bias': (3,)}
    result = {'body.input.weight': (8, 1, 1), 'body.input.bias': (8,),
              'head.weight': (3, 8), 'head.bias': (3,)}
    for index in range(3):
        result[f'body.layers.{index}.weight'] = (8, 8, 3)
        result[f'body.layers.{index}.bias'] = (8,)
    return result


def validate_tensor(value: object, dimensions: tuple) -> None:
    if not dimensions:
        if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 3e38:
            raise ValueError('invalid finite float32 neural weight')
        return
    if not isinstance(value, list) or len(value) != dimensions[0]:
        raise ValueError('neural tensor shape does not match architecture')
    for item in value:
        validate_tensor(item, dimensions[1:])


def validate_artifact(artifact: dict) -> dict:
    shape(artifact, {'schema', 'config', 'instrument', 'source', 'currency', 'adjustment',
                     'interval', 'known_at', 'data_last_at', 'dataset_sha256', 'evidence_ids',
                     'weights', 'scaler', 'calibration', 'parameter_count', 'fit', 'evaluation',
                     'framework', 'dtype', 'execution_eligible', 'model_id'})
    if len(canonical(artifact).encode('utf-8')) > MAX_BYTES:
        raise ValueError('neural artifact exceeds size limit')
    expected = 'nn-' + fingerprint({key: value for key, value in artifact.items() if key != 'model_id'})
    if artifact['model_id'] != expected or artifact['schema'] != SCHEMA:
        raise ValueError('invalid neural artifact checksum or schema')
    config(artifact['config'])
    if artifact['dtype'] != 'float32' or artifact['execution_eligible'] is not False:
        raise ValueError('invalid neural precision or execution authority')
    text(artifact['instrument'], INSTRUMENT)
    text(artifact['source'])
    text(artifact['currency'], CURRENCY)
    if timestamp(artifact['data_last_at']) > timestamp(artifact['known_at']):
        raise ValueError('future artifact data')
    if not isinstance(artifact['dataset_sha256'], str) or not re.fullmatch('[0-9a-f]{64}', artifact['dataset_sha256']):
        raise ValueError('invalid dataset digest')
    if artifact['evaluation'].get('point_in_time_market_backtest') is not False:
        raise ValueError('retrospective evaluation cannot claim a market backtest')
    if artifact['adjustment'] not in ('split', 'total_return') or artifact['interval'] != '1d':
        raise ValueError('invalid neural artifact price semantics')
    bounded_int(artifact['parameter_count'], 1, 10000)
    if not isinstance(artifact['evidence_ids'], list) or not 2 <= len(artifact['evidence_ids']) <= MAX_ROWS:
        raise ValueError('invalid neural artifact evidence')
    for event_id in artifact['evidence_ids']:
        text(event_id)
    if len(set(artifact['evidence_ids'])) != len(artifact['evidence_ids']):
        raise ValueError('duplicate artifact evidence')
    shapes = weight_shapes(artifact['config'])
    if not isinstance(artifact['weights'], dict) or artifact['weights'].keys() != shapes.keys():
        raise ValueError('invalid neural weight names')
    if artifact['parameter_count'] != sum(math.prod(dimensions) for dimensions in shapes.values()):
        raise ValueError('invalid neural parameter count')
    for name, dimensions in shapes.items():
        validate_tensor(artifact['weights'][name], dimensions)
    shape(artifact['scaler'], {'x_mean', 'x_scale', 'y_mean', 'y_scale'})
    for value in artifact['scaler'].values():
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('invalid neural scaler')
    if artifact['scaler']['x_scale'] <= 0 or artifact['scaler']['y_scale'] <= 0:
        raise ValueError('invalid neural scaler scale')
    if (type(artifact['calibration']) not in (int, float) or not math.isfinite(artifact['calibration'])
            or artifact['calibration'] < 0):
        raise ValueError('invalid calibration radius')
    return artifact
