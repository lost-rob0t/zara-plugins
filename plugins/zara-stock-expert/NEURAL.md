# Neural research layer

Unreleased 0.1.0 continuation. Two real PyTorch models, not an LLM pretending to run a neural network. This layer is disabled by default, performs no brokerage actions, and does not alter exact-money calculations or Prolog trade preflight. Read [the research and limitations](RESEARCH.md) before interpreting diagnostics.

## Enable

Install the optional CPU dependency in the Python environment that runs Zara. The tested dependency is PyTorch 2.10.0; it is not automatically downloaded by the plugin:

```sh
python -m pip install 'torch==2.10.0' --index-url https://download.pytorch.org/whl/cpu
```

Add this to the existing **plugin-local** runtime configuration, retaining the database, namespace and any market/Prolog settings:

```json
{
  "database": "/absolute/private/path/market.sqlite3",
  "namespace": "research",
  "neural": {
    "enabled": true,
    "timeout_seconds": 60,
    "history_limit": 512,
    "max_epochs": 100,
    "max_bar_age_days": 7
  }
}
```

This is the existing Python runtime-settings surface, not a newly implemented executable-Prolog configuration bridge. No Android-local neural runtime, Nix neural dependency closure, GPU mode, pretrained downloads, or cross-plugin discovery was added.

## Supply actual daily history

The existing `stock.fetch_quote` still fetches GLOBAL_QUOTE with unknown adjustment semantics. **It cannot supply the adjusted training series.** A trusted stock API adapter must call the new in-process `service.ingest_bar(observation)` method. It is not exposed as an LLM tool.

```python
service.ingest_bar({
    "event_id": "provider-series-revision-20260916",
    "instrument": "XNAS:EXAMPLE",
    "source": "configured-provider",
    "effective_at": "2026-09-16T20:00:00+00:00",
    "close": "100.12340000",
    "currency": "USD",
    "adjustment": "split",
    "interval": "1d",
    "session_index": 1234
})
```

This is a fictional schema example, not a provider observation or an exchange-calendar claim. The adapter must establish the real instrument mapping, close timestamp, adjustment basis and consecutive expected exchange-session indices. Never label raw/unknown prices adjusted. Never manufacture timestamps, fill missing sessions silently, or pass model notes as observations. `split` and `total_return` are distinct accepted adjustment bases. Use a new event ID and `supersedes` for a correction. Prices remain exact decimal strings in SQLite; only the isolated ML boundary converts them to floating-point returns.

The default window is the latest 512 closes, with explicit truncation metadata and a hard maximum of 1,000. This is a bounded working window over a persistent KB, not unlimited training. At least 32 training samples, 16 validation samples, 16 calibration samples, 16 test samples per fold, plus context and purge gaps are required. The exact minimum depends on horizon and fold count; insufficient history is an error.

## Tools

`stock.neural_train(instrument, source, architecture="tcn", lookback=16, horizon=1, epochs=40, folds=3, seed=17)` trains and persists a model card. Architectures are `mlp` and `tcn`; context is 8–64 sessions, horizon 1–20, folds 1–4, and epochs 1–200 subject to the lower operator cap. This is a persistent write and carries `zara_requires_approval`.

`stock.neural_forecast(model_id)` uses the registered model and current trusted history, checks the last bar's age, and persists a separately labelled `model_forecast` event. It also carries approval metadata. Output is three **log-return quantiles**, not share quantities, account money, an expected-profit promise or a buy instruction. `execution_eligible=false` and `coverage_guaranteed=false` are mandatory. A standardized input beyond eight training standard deviations produces `disposition="abstain"`; this is a simple diagnostic, not a complete regime detector.

`stock.neural_models(instrument, limit=20)` returns cards, data hashes and all fold diagnostics without weights. Model weights, scalers, source, currency, adjustment basis, knowledge cutoff, framework version and evidence IDs persist in the namespace-scoped SQLite model table. Model rows cannot be updated/deleted through ordinary table operations. This is not encryption or protection against an operator replacing the database.

## Runtime and limits

Zara's existing bounded mailbox remains the sole SQLite owner. Numerical work runs outside it in one supervised child process per request, with one in-flight computation, one numerical thread, a 5–120 second deadline, fixed executable/module path and a credential-filtered environment. Shutdown and timeout kill the child. This is process isolation, **not an OS security sandbox or a hard heap quota**. The trusted worker enforces a 512 KiB JSON result limit, and the parent rejects oversized results; the parent does not provide a hostile-process streaming memory sandbox.

No pickle, `torch.load`, model file paths, remote code or weight downloads are accepted. JSON weights are validated against the fixed architecture, dimensions, finite float32 values, parameter count and content digest. Digests identify content; they do not authenticate a provider. Missing PyTorch fails explicitly on use and does not disable the money tools.

## Verification

```sh
PYTHONPATH=plugins/zara-stock-expert/lib \
  python -m unittest discover -s plugins/zara-stock-expert/test -v
```

The dedicated integration workflow installs CPU PyTorch, the pinned real Zara market contract and SWI-Prolog. It rejects skipped tests and exercises real StructuredTools, model training, persistence, forecasting, money and Prolog. The provider HTTP response and the neural dataset are fixtures. No authenticated provider data, installed-user device, investment result or live execution is implied by these tests.
