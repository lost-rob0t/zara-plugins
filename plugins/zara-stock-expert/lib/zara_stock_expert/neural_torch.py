from __future__ import annotations

import math

import torch
from torch import nn
from torch.nn import functional as functional

from .neural import (QUANTILES, SCHEMA, config, dataset, fingerprint, folds, partition,
                     seal, series, validate_artifact)
from .domain import timestamp


class CausalFeatures(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.input = nn.Conv1d(1, 8, 1)
        self.layers = nn.ModuleList([nn.Conv1d(8, 8, 3, dilation=d) for d in (1, 2, 4)])

    def forward(self, values):
        values = self.input(values)
        for dilation, layer in zip((1, 2, 4), self.layers):
            values = values + functional.silu(layer(functional.pad(values, (2 * dilation, 0))))
        return values


class QuantileNetwork(nn.Module):
    def __init__(self, options: dict) -> None:
        super().__init__()
        self.architecture = options['architecture']
        if self.architecture == 'mlp':
            self.body = nn.Sequential(nn.Linear(options['lookback'], 16), nn.Tanh(),
                                      nn.Linear(16, 16), nn.Tanh(), nn.Linear(16, 3))
        else:
            self.body = CausalFeatures()
            self.head = nn.Linear(8, 3)

    def forward(self, values):
        raw = self.body(values) if self.architecture == 'mlp' else self.head(self.body(values[:, None, :])[:, :, -1])
        middle = raw[:, 0]
        return torch.stack((middle - functional.softplus(raw[:, 1]), middle,
                            middle + functional.softplus(raw[:, 2])), dim=-1)


def pinball(prediction, target):
    error = target[:, None] - prediction
    quantiles = prediction.new_tensor(QUANTILES)
    return torch.maximum(quantiles * error, (quantiles - 1) * error).mean()


def weights(model) -> dict:
    return {name: value.detach().cpu().tolist() for name, value in model.state_dict().items()}


def _slice(values, bounds):
    return values[bounds[0]:bounds[1]]


def _fit(x, y, plan: dict, options: dict):
    torch.manual_seed(options['seed'])
    model = QuantileNetwork(options).float()
    train_x, train_y = _slice(x, plan['train']), _slice(y, plan['train'])
    scaler = dict(x_mean=float(train_x.mean()), x_scale=max(float(train_x.std(unbiased=False)), 1e-6),
                  y_mean=float(train_y.mean()), y_scale=max(float(train_y.std(unbiased=False)), 1e-6))
    scaled_x = (x - scaler['x_mean']) / scaler['x_scale']
    scaled_y = (y - scaler['y_mean']) / scaler['y_scale']
    optimizer = torch.optim.Adam(model.parameters(), lr=0.003, weight_decay=0.001)
    best_loss, best_epoch, best_state = math.inf, 0, None
    for epoch in range(options['epochs']):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        loss = pinball(model(_slice(scaled_x, plan['train'])), _slice(scaled_y, plan['train']))
        if not torch.isfinite(loss):
            raise ValueError('non-finite neural training loss')
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
        optimizer.step()
        model.eval()
        with torch.no_grad():
            validation = float(pinball(model(_slice(scaled_x, plan['validation'])),
                                       _slice(scaled_y, plan['validation'])))
        if not math.isfinite(validation):
            raise ValueError('non-finite validation loss')
        if validation < best_loss:
            best_loss, best_epoch = validation, epoch + 1
            best_state = {name: tensor.detach().clone() for name, tensor in model.state_dict().items()}
        if epoch + 1 - best_epoch >= 8:
            break
    assert best_state is not None and best_epoch > 0
    model.load_state_dict(best_state, strict=True)
    model.eval()
    with torch.no_grad():
        predictions = model(scaled_x) * scaler['y_scale'] + scaler['y_mean']
    if not torch.isfinite(predictions).all():
        raise ValueError('non-finite neural predictions')
    cal_q = _slice(predictions, plan['calibration'])
    cal_y = _slice(y, plan['calibration'])
    scores = torch.maximum(cal_q[:, 0] - cal_y, cal_y - cal_q[:, 2]).clamp_min(0).sort().values
    rank = math.ceil((len(scores) + 1) * 0.8)
    if rank > len(scores):
        raise ValueError('insufficient calibration scores for nominal 80 percent interval')
    radius = float(scores[rank - 1])
    predictions[:, 0] -= radius
    predictions[:, 2] += radius
    fit = dict(partition=plan, best_epoch=best_epoch, epochs_run=epoch + 1,
               validation_pinball_scaled=best_loss, calibration_count=len(scores))
    return model, scaler, radius, predictions, fit


def _ridge(x, y, plan, scaler):
    scaled = ((x.double() - scaler['x_mean']) / scaler['x_scale'])
    design = torch.cat((torch.ones((len(x), 1), dtype=torch.float64), scaled), dim=1)
    train = _slice(design, plan['train'])
    penalty = torch.eye(design.shape[1], dtype=torch.float64)
    penalty[0, 0] = 1e-8
    coefficients = torch.linalg.solve(train.T @ train + penalty, train.T @ _slice(y.double(), plan['train']))
    return (design @ coefficients).float()


def _metrics(prediction, target, ridge) -> dict:
    return dict(mae=float((prediction[:, 1] - target).abs().mean()),
                zero_return_mae=float(target.abs().mean()),
                ridge_mae=float((ridge - target).abs().mean()),
                pinball_loss=float(pinball(prediction, target)),
                coverage_80=float(((target >= prediction[:, 0]) & (target <= prediction[:, 2])).float().mean()),
                mean_interval_width=float((prediction[:, 2] - prediction[:, 0]).mean()))


def train(snapshot: dict, options: dict) -> dict:
    options = config(options)
    data = dataset(snapshot, options)
    plans = folds(len(data['y']), options)
    x, y = torch.tensor(data['x'], dtype=torch.float32), torch.tensor(data['y'], dtype=torch.float32)
    reports = []
    for plan in plans:
        model, scaler, _, prediction, fit = _fit(x, y, plan, options)
        ridge = _ridge(x, y, plan, scaler)
        report = _metrics(_slice(prediction, plan['test']), _slice(y, plan['test']), _slice(ridge, plan['test']))
        reports.append(dict(metrics=report, scaler=scaler, weights_sha256=fingerprint(weights(model)), **fit))
    aggregate = {key: sum(report['metrics'][key] for report in reports) / len(reports)
                 for key in reports[0]['metrics']}
    final_plan = partition(len(y), options['horizon'])
    model, scaler, radius, _, fit = _fit(x, y, final_plan, options)
    fit['last_gradient_label_at'] = snapshot['records'][data['label_ends'][final_plan['train'][1] - 1]]['effective_at']
    fit['last_calibration_label_at'] = snapshot['records'][data['label_ends'][final_plan['calibration'][1] - 1]]['effective_at']
    artifact = dict(schema=SCHEMA, config=options, weights=weights(model), scaler=scaler,
                    calibration=radius, fit=fit, parameter_count=sum(p.numel() for p in model.parameters()),
                    framework='torch-' + torch.__version__, dtype='float32', execution_eligible=False,
                    known_at=snapshot['known_at'], data_last_at=snapshot['records'][-1]['effective_at'],
                    dataset_sha256=fingerprint(snapshot), evidence_ids=[row['event_id'] for row in snapshot['records']],
                    evaluation=dict(folds=reports, aggregate=aggregate, point_in_time_market_backtest=False,
                        interpretation='retrospective snapshot diagnostics; not trading P&L or profitability evidence',
                        history_truncated=snapshot['history_truncated'], trial_correction='not_implemented'))
    artifact.update({key: snapshot[key] for key in ('instrument', 'source', 'currency', 'adjustment', 'interval')})
    return validate_artifact(seal(artifact))


def _restore(artifact: dict):
    validate_artifact(artifact)
    model = QuantileNetwork(config(artifact['config'])).float()
    expected, supplied = model.state_dict(), artifact['weights']
    if expected.keys() != supplied.keys():
        raise ValueError('neural weight names do not match the allowlisted architecture')
    tensors = {}
    for name, template in expected.items():
        try:
            tensor = torch.tensor(supplied[name], dtype=torch.float32)
        except (TypeError, ValueError, RuntimeError) as error:
            raise ValueError('invalid neural weight tensor') from error
        if tensor.shape != template.shape or not torch.isfinite(tensor).all():
            raise ValueError('invalid neural tensor shape or non-finite weights')
        tensors[name] = tensor
    model.load_state_dict(tensors, strict=True)
    model.eval()
    return model


def forecast(artifact: dict, snapshot: dict) -> dict:
    model = _restore(artifact)
    prices = series(snapshot)
    if any(snapshot[key] != artifact[key] for key in ('instrument', 'source', 'currency', 'adjustment', 'interval')):
        raise ValueError('forecast series does not match the trained model')
    if (timestamp(snapshot['known_at']) < timestamp(artifact['known_at'])
            or timestamp(snapshot['records'][-1]['effective_at']) < timestamp(artifact['data_last_at'])):
        raise ValueError('cannot apply a future model to past data')
    lookback = artifact['config']['lookback']
    if len(prices) <= lookback:
        raise ValueError('insufficient forecast context')
    context = [math.log(right / left) for left, right in zip(prices, prices[1:])][-lookback:]
    scaler = artifact['scaler']
    x = (torch.tensor([context], dtype=torch.float32) - scaler['x_mean']) / scaler['x_scale']
    with torch.no_grad():
        q = (model(x)[0] * scaler['y_scale'] + scaler['y_mean']).tolist()
    q[0] -= artifact['calibration']
    q[2] += artifact['calibration']
    if not all(math.isfinite(value) for value in q) or not q[0] <= q[1] <= q[2]:
        raise ValueError('invalid neural forecast')
    drift = bool((x.abs() > 8).any())
    return dict(model_id=artifact['model_id'], architecture=artifact['config']['architecture'],
                instrument=artifact['instrument'], model_dataset_sha256=artifact['dataset_sha256'],
                input_sha256=fingerprint(snapshot), as_of=snapshot['known_at'],
                data_last_at=snapshot['records'][-1]['effective_at'],
                horizon_observed_sessions=artifact['config']['horizon'], quantile_levels=list(QUANTILES),
                log_return_quantiles=q, target='adjusted_close_log_return',
                nominal_interval_coverage=0.8, coverage_guaranteed=False, execution_eligible=False,
                input_out_of_training_range=drift,
                disposition='abstain' if drift else 'research_forecast',
                warnings=['not_a_trade_signal', 'retrospective_evaluation_not_profitability_evidence'])
