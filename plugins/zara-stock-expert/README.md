# zara-stock-expert 0.1.0

Persistent market research, exact money mathematics, and a bounded Prolog stock
risk expert for Zara. This is an unreleased integration update to draft PR #810.
It creates research records and paper candidates, **not broker orders**. It is
not a stock-picking strategy, a profitability claim, a backtesting engine, a
portfolio accountant, or a tax-lot ledger.

## Configure

Zara passes only `[plugins.zara-stock-expert]` to this plugin's runtime. The old
whole-config wrapper is accepted for compatibility, but do not mix both shapes.
An empty configuration leaves storage unavailable; pure money calculations work.

```toml
[plugins.zara-stock-expert]
database = "/home/YOUR_USER/.local/share/zarathushtra/zara-stock-expert/market.sqlite3"
namespace = "personal-research"
max_quote_age_seconds = 60
prolog_enabled = true

[plugins.zara-stock-expert.market_data]
api_key_env = "ALPHAVANTAGE_API_KEY"
timeout_seconds = 3

[plugins.zara-stock-expert.market_data.instruments."XNAS:EXAMPLE"]
symbol = "EXAMPLE"
currency = "USD"
```

`EXAMPLE` is a fictional test symbol, not an investment recommendation. Replace
it with an explicitly verified provider symbol, venue-qualified instrument, and
currency mapping. The mapping is operator-supplied; GLOBAL_QUOTE does not itself
verify its currency and venue. Do not assume that every symbol is USD.

Put the actual provider credential in the named environment variable, not in the
KB, prompt, repository, or tool arguments. The adapter only permits Alpha
Vantage's HTTPS endpoint; redirects, custom endpoints, and inline keys are not
accepted by this adapter. Trusted executable Prolog remains a separate code
boundary; these restrictions are not a sandbox for operator-owned Prolog code.

### Dependencies and activation

- The market adapter imports the actual `MarketDataClient` and
  `MarketProviderConfig` introduced by **lost-rob0t/zara PR #929**. The dedicated
  integration gate pins Zara commit `fadd071682811d3597635fcc7e890a84e3165bff`.
  This is an explicit cross-repository dependency, not a claim that #929 merged.
- Prolog mode requires the `zara_expert` library from the **zara-expert** plugin
  and `swipl` on PATH. Install/load zara-expert alongside this plugin. A standalone
  stock package does not bundle SWI-Prolog. In a source checkout, add
  `plugins/zara-expert/lib` to PYTHONPATH.
- Omit `market_data` for a local KB with no network access. Omit `prolog_enabled`
  or set it to false for Python preflight only. Explicitly enabling an unavailable
  dependency fails startup; it does not silently claim to run Prolog.

The database must be an absolute path outside `/nix/store`. Its leaf directory
must be private (0700); the database must be a private regular file (0600), not a
symlink. Use one configured instance per trusted operator. This is neither
end-to-end encryption nor a multi-tenant authorization service.

## Tools

| Tool | Purpose |
| --- | --- |
| `stock.status()` | Storage, market-adapter and Prolog-registration status; execution remains disabled. |
| `stock.fetch_quote(instrument)` | Fetch an operator-mapped symbol through the actual Zara provider client and persist the observation. Requires host approval. |
| `stock.report_quote(observation_json)` | Retain a model-relayed quote as **unverified**, never provider evidence. Requires approval. |
| `stock.remember_note(event_id, instrument, note, source)` | Persist a research note or hypothesis separately from market facts. Requires approval. |
| `stock.history(instrument, effective_at, known_at, limit, revisions)` | Retrieve bounded point-in-time evidence and optionally all immutable revisions. |
| `stock.money(operation, arguments_json)` | Exact decimal-string addition, P&L, break-even, and long-only sizing. |
| `stock.evaluate(instrument, sizing_json, mode)` | Run Python risk preflight using KB evidence and return blockers. |
| `stock.explain(instrument, sizing_json, mode)` | Run that assessment through the registered SWI-Prolog rules and return actual Prolog results and trace. |

The three persistent-write tools declare `zara_requires_approval` metadata.
Authorization and consent enforcement belong to the host. Direct Python calls
are trusted code, not an alternative LLM authorization mechanism. Neither
`ingest_quote` nor unrestricted Prolog queries are exposed as stock tools.

## Exact provider ingestion

`stock.fetch_quote` uses Zara's real provider client with an exact-decimal
numeric conversion override. It does not stringify an already-rounded float.
A bounded JSON transport rejects duplicate keys, non-finite JSON constants,
non-object JSON, malformed UTF-8, and responses over 16 KiB. Only one provider
request per plugin instance may be in flight. Transport/provider failures are
redacted so exception messages cannot return an API key or provider-echoed URL.
The timeout setting controls network I/O and a read-loop deadline; it is not a
claim of a hard end-to-end wall-clock deadline covering DNS and every HTTP phase.
There is no polling scheduler, automatic retry loop, broker client, or order API.

Alpha Vantage documents that GLOBAL_QUOTE defaults to end-of-day updates:
<https://www.alphavantage.co/documentation/#latestprice> (checked 2026-09-17).
This adapter does not request a realtime entitlement. Therefore it stores:

```json
{
  "feed": "historical",
  "adjustment": "unknown",
  "timestamp_precision": "day",
  "trading_day": "2026-09-16"
}
```

`effective_at` is a **UTC date index** (`2026-09-16T00:00:00Z`), not a claimed
exchange timestamp or closing instant. Precision and trading date remain in the
stored payload. Day-precision observations cannot be relabelled realtime, use an
intraday index, or pass the realtime preflight. Unknown adjustment semantics also
block that preflight. A current download is not necessarily a current quote.
These records are useful for research, but this adapter alone intentionally does
not create realtime paper candidates.

The event ID is a deterministic content hash. Identical provider observations
return the existing record; changed observations get distinct IDs. This is not
a vendor-certified revision relationship. Explicit corrections remain available
at the trusted ingestion boundary and preserve their full predecessor chain.

Other trusted provider adapters may call the started plugin's `ingest_quote()`:

```python
plugin.ingest_quote({
    "event_id": "provider:stable-id",
    "instrument": "XNAS:EXAMPLE",
    "source": "your-provider",
    "effective_at": "2026-09-17T14:30:00+00:00",
    "price": "100.00",
    "currency": "USD",
    "adjustment": "raw",
    "feed": "realtime",
    "price_kind": "last"
})
```

Those are fictional fixture values. The trusted adapter must preserve the source
lexical decimal, correct instrument/currency, actual timestamp, feed entitlement,
and adjustment semantics. `provider_adapter` identifies this ingestion path; it
is not a cryptographic proof that provider data is correct.

## Actor ownership and persistent knowledge

One 64-message mailbox, owned by Zara's `PluginRuntime.start_worker()`, serializes
SQLite and Prolog operations. Messages are capped at 16 KiB. The database
connection never crosses Python threads. Idle workers block rather than spin.
Provider HTTP runs outside this database owner, so a provider request does not
occupy the KB mailbox.

Mailbox calls time out after five seconds. A queued timed-out operation is
cancelled before execution. An already-running write has an **unknown outcome**;
retry its identical event ID. Shutdown drains queued work with explicit errors.
The host's managed-worker failure reporting remains authoritative.

SQLite uses WAL and FULL synchronization, namespace-scoped event IDs, and
no-update/no-delete triggers. Research notes always have `model_note` provenance,
even when their source label sounds authoritative. Model reports cannot replace
provider observations or become verified facts. Notes are limited to 4096 UTF-8
bytes. The OS owner can still alter the database: this is not a tamper-proof ledger.

`effective_at` constrains applicability and `known_at` constrains the KB's actual
recording time. Both are applied before hiding superseded records. Late arrivals
and later corrections therefore do not leak into an earlier knowledge snapshot.
An explicit correction must preserve namespace, instrument, source, kind,
provenance and effective time; each predecessor can have only one successor.

History returns newest-first records, at most 1000, and a `truncated` flag.
Pagination, OHLCV ingestion, fundamentals, corporate-action events and tax lots
are not implemented. There is no automatic retention deletion; monitor disk
space. Use SQLite's backup API or stop the service for backup; copying only the
main file while WAL writes are active is not a consistent backup procedure.

## Money mathematics

All amount inputs are bounded plain decimal strings: at most 18 integer and
12 fractional digits. Floats, booleans, exponents, NaN, infinity, malformed values,
and unknown fields are rejected. Parsing and intermediate arithmetic use exact
rational values; rounding occurs only at explicit output boundaries.

Each operation uses one currency. Addition validates both currency codes. There
is no implicit FX conversion or lookup of settlement scales. `places` defaults
to 2; configure the appropriate precision explicitly.

- `add`: `left` and `right` objects containing `amount` and `currency`; optional
  `places`. Output uses half-even rounding.
- `pnl`: `currency`, `quantity`, `entry`, `exit`, `entry_fee`, `exit_fee`; optional
  `places`. Returns cost basis, proceeds, gross P&L and net P&L.
- `break_even`: `currency`, `quantity`, `entry`, `entry_fee`, `exit_fee`,
  `price_tick`; optional `places`. Rounds the break-even price up to a price tick.
- `position_size`: the complete fictional example below. Quantity is floored to
  the allowed step and capped by cash, stop-loss risk and existing exposure.

```json
{
  "currency": "USD", "equity": "10000", "cash": "1000",
  "entry": "100", "stop": "95", "risk_fraction": "0.01",
  "max_position_fraction": "0.10", "entry_fee": "1", "exit_fee": "1",
  "quantity_step": "1", "price_tick": "0.01", "slippage_per_share": "0.50",
  "existing_exposure": "0"
}
```

This fixture yields 9 shares, $901.00 required cash, $51.50 estimated stop-loss
cost, and a $100.00 risk budget. Displayed costs round up and budgets round down.
Cash/equity/exposure inputs are scenario inputs, not authenticated account data.
A stop price does not guarantee execution or cap the actual loss; gaps, fees,
liquidity and slippage can invalidate the assumptions.

## Actual Prolog execution

When enabled, startup constructs an existing `zara_expert.domain.ExpertHost`,
registers `stock_host.pl`, and loads the bundled `zara_stock_trading` module.
This is a stock-owned host instance, not registration in another running
plugin's global object. Namespaces are derived from database path and configured
namespace. The bounded backend is `SwiplBackend`: one second, one solution,
16 KiB per output stream. No raw model-authored goal is accepted.

`stock.explain` first calculates a new Python assessment on the database worker.
It then constructs a validated goal such as:

```prolog
stock_trade_explain(assessment(paper, [not_realtime]), Explanation).
```

The response contains the Python `assessment`, actual Prolog `results` and
`trace`, the engine and namespace, and `executable: false`. No solution, a missing
engine, timeout or backend failure is an explicit error, not a Python fallback
labelled as Prolog. These rules explain risk blockers; they do not generate a
stock-picking signal. `stock.evaluate` remains explicitly Python preflight.
Trusted Prolog-to-Python configuration synchronization and Android-local
execution are not implemented in this plugin.

## Tests and release gates

```sh
python3 -m unittest discover -s plugins/zara-stock-expert/test -v
```

The standard-library suite tests monetary bounds, persistence, corrections,
idempotency, trust separation, actor lifecycle, configuration, provider mapping,
day precision, redaction and bounded transport. Real-runtime tests skip when
required packages/SWI are absent from an ordinary local development environment.

`.github/workflows/stock-expert-integration.yml` installs SWI-Prolog and loads
the exact Zara source contract plus the repository's zara-expert library. It
runs the actual market normalizer, StructuredTools, PluginRuntime, SQLite KB,
and Prolog subprocess; **only provider HTTP is mocked**. The gate fails on any
skip and records dependency versions. It does not claim a live credentialed
provider request, Android installation, broker execution, or strategy returns.

This update remains in draft PR #810 pending exact-head CI and the repository's
independent review/voting requirements. No merge or independent reviewer vote
is implied by local tests.
