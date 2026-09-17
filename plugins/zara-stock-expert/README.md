# zara-stock-expert 0.1.0

A stock **risk expert**, durable market knowledge base and exact-money tool for
Zara. It does not pretend an LLM is a calculator, treat a remembered hypothesis
as a market fact, or turn an analysis into a broker order.

This first version is long-only, single-currency per calculation, and
paper-proposal-only. It is not a stock-picking strategy, a backtesting engine,
a brokerage integration, a portfolio accountant or a profitability claim.

## Components and ownership

The stock API adapter supplies observations. One bounded mailbox (64 messages,
16 KiB each) on Zara's existing `PluginRuntime.start_worker()` owns the SQLite
connection. The database is not shared across Python threads. Idle workers block;
there is no stock poller, independent scheduler, shell execution or network client.
Calls time out after five seconds. A queued timed-out call is cancelled before
execution. A running timed-out write has **unknown outcome**: retry its identical
`event_id`, do not make up a new ID and accidentally duplicate it.

The expert stores quotes and model notes. Quotes include a venue-qualified
instrument ID, decimal-string price, currency, price kind (bid/ask/last), feed
(realtime/delayed/historical), adjustment (raw/split/total_return), source,
effective time and server-assigned recorded time. This version does not ingest
OHLCV bars, fundamentals, dividends, split events or tax lots.

## Configure the service

Zara service configuration uses the existing plugin runtime mapping. Configure an
absolute private path and an operator-owned namespace; an absent section leaves
storage unavailable while pure money calculations remain usable.

```toml
[plugins.zara-stock-expert]
database = "/home/YOUR_USER/.local/share/zarathushtra/zara-stock-expert/market.sqlite3"
namespace = "personal-research"
max_quote_age_seconds = 60
```

Use the relevant XDG data directory on your machine. The leaf directory must be
private (0700) and the database private (0600). No symlink leaf or `/nix/store`
state path is accepted. Namespace selection is operator configuration, not a
model-supplied tool argument. This is single-operator local state: do not share a
configured instance among untrusted tenants. It is not encryption or an external
authorization service.

## Stock API integration contract

A trusted in-process provider adapter calls the started plugin instance:

```python
expert_plugin.ingest_quote({
    "event_id": "provider:stable-response-id",
    "instrument": "XNAS:EXAMPLE",
    "source": "your-configured-provider",
    "effective_at": "2026-09-17T14:30:00+00:00",
    "price": "100.00",
    "currency": "USD",
    "adjustment": "raw",
    "feed": "realtime",
    "price_kind": "last"
})
```

These are fictional fixture values, not a current market quote. Decimal values
must come directly from the source's lexical representation. Preserve JSON
numbers using a decimal-aware parser at the stock API boundary; do not parse to
binary floats and then stringify them. The adapter must truthfully label feed,
exchange/instrument, currency and timestamp semantics.

`ingest_quote` is deliberately **not** an LLM tool. `provider_adapter` means the
trusted in-process adapter submitted it, not that a string proves authenticity.
The stock API plugin still needs to wire this method to its actual validated
provider response. No live provider integration was available to verify here.

`stock.report_quote` can retain data relayed through an LLM, but assigns immutable
`unverified_report` provenance. Model reports cannot supersede trusted provider
records and cannot pass the paper preflight. `stock.remember_note` is always a
model note, even when its source label says something authoritative.

## Tools

| Tool | Behavior |
| --- | --- |
| `stock.status` | Configuration, policy freshness bound and no-live-execution status. |
| `stock.report_quote(observation_json)` | Approval-gated persistence of an unverified structured quote. |
| `stock.remember_note(event_id, instrument, note, source)` | Approval-gated long-term hypothesis or research note, limited to 4096 UTF-8 bytes. |
| `stock.history(instrument, effective_at, known_at, limit, revisions)` | Bounded evidence retrieval, with explicit truncation and optional revision history. |
| `stock.money(operation, arguments_json)` | Stateless exact-money calculations. |
| `stock.evaluate(instrument, sizing_json, mode)` | Deterministic risk preflight against stored evidence; never submits an order. |

The two persistence tools declare Zara's `zara_requires_approval` metadata.
Host approval and principal enforcement remain the host's responsibility; direct
Python method calls are a trusted-code boundary, not a security sandbox.

## Long-term memory semantics

SQLite uses WAL and FULL synchronous mode. Records are append-only through this
API and protected by no-update/no-delete triggers. The operating-system owner can
still edit the file or schema; this is not a tamper-proof ledger.

Each namespace has stable event IDs. Identical retries return the original
record and timestamp. Different content under an existing ID is a conflict.
Corrections use a new ID and `supersedes`; the predecessor must already exist in
the same namespace, instrument, source, effective time, kind and provenance.
Each predecessor has at most one successor. Prior revisions are retained.

`effective_at` answers when a fact applies; `known_at` limits when the system had
actually recorded it. Both filters are applied before hiding superseded records.
A later correction or late import therefore does not leak into an earlier
knowledge snapshot. This does not fix survivorship bias, vendor vintage errors,
incorrect source timestamps or wall-clock problems at the adapter boundary.

History returns the newest records first, at most 1000 per call, and a
`truncated` flag. There is no bulk pagination/export tool in this version. Use
SQLite's backup API or stop the service for a consistent backup; copying only the
main database while WAL writes are active is not a backup procedure. There is no
automatic deletion or retention cap; monitor disk space.

## Exact-money mathematics

Inputs are plain decimal strings with at most 18 integer and 12 fractional
digits. Booleans, floats, exponents, NaN, infinity, invalid signs and unknown
fields are rejected. Decimal parsing and rational intermediates preserve exact
values; only explicit output boundaries round. No `eval` or generated arithmetic
code is involved.

`currency` denotes the currency of **all** amounts within that operation.
`places` defaults to 2 and is explicit, not inferred from a currency table; use
0 for whole-unit settlement or a different scale where appropriate. Addition
checks both currency codes; FX conversion is not implemented. Currency-code
syntax is validated, not membership in a live currency registry.

Operations:

- `add`: `left` and `right` money objects (`amount`, `currency`), optional `places`.
- `pnl`: `currency`, `quantity`, `entry`, `exit`, `entry_fee`, `exit_fee`, optional
  `places`. Returns gross/net P&L, cost basis and proceeds, with half-even rounding.
- `break_even`: `currency`, `quantity`, `entry`, `entry_fee`, `exit_fee`,
  `price_tick`, optional `places`. Returns the price rounded **up** to the next
  specified tick, including both fees.
- `position_size`: see the complete example below. Rounds quantity down to the
  allowed step, estimated cash/loss up to the specified currency places, and
  displayed risk budget down. Exact internal comparisons enforce the limits.

```json
{
  "currency": "USD",
  "equity": "10000",
  "cash": "1000",
  "entry": "100",
  "stop": "95",
  "risk_fraction": "0.01",
  "max_position_fraction": "0.10",
  "entry_fee": "1",
  "exit_fee": "1",
  "quantity_step": "1",
  "price_tick": "0.01",
  "slippage_per_share": "0.50",
  "existing_exposure": "0"
}
```

This fictional sizing example returns **9 shares**, **USD 901.00** entry cash,
**USD 51.50** estimated stop loss including fees/slippage, and a **USD 100.00**
risk budget. Cash, risk and total instrument exposure independently cap quantity.
The assumed slippage is not a worst-case bound: gaps, liquidity, fees, execution
and stops can differ. `loss_bound_guaranteed` is always false.

Equity, cash, risk limits, fees and exposure here are caller-supplied scenario
inputs. They are not authenticated broker balances. This is not an enforcement
gateway for a brokerage account. No margin, shorts, options, FX, taxes, corporate
actions, borrow charges or order-fill simulation are implemented.

## Expert reasoning and Prolog

`stock.evaluate` uses receipt-time evidence and operator-configured quote age.
It blocks missing/unverified/stale/delayed/adjusted evidence, currency or entry
price mismatches, zero affordable quantity, and live mode. A passing result is
only `paper_candidate`, with `executable=false`, policy version, evidence IDs,
evaluation timestamp, exact sizing and the input hash. `strategy_signal` is
`not_evaluated`; passing risk checks is not a buy recommendation or simulated fill.
The result is returned, not automatically persisted as a trade ledger.

The package also includes an ordinary executable Prolog module:
`lib/zara_stock_expert/stock_trading.pl`. Load it through your trusted Prolog
configuration or the existing expert host's operator-owned KB registration:

```prolog
?- use_module('/absolute/path/to/stock_trading.pl').
?- stock_trade_decision(assessment(paper, [stale_quote]), Decision).
Decision = blocked.

?- stock_trade_explain(assessment(paper, []), Explanation).
Explanation = explanation(paper_candidate,
                         [risk_checks_passed, strategy_not_evaluated, no_execution]).
```

The module's `_decision` and `_explain` entry points are exported. Its assessment
input is a projection of the checked tool result, not permission to erase
blockers. It contains no float calculations. Trusted configuration remains
executable Prolog and can compose strategies, rules, scheduling or API calls;
this package does not redefine it as a restricted data format.

Automatic registration into the expert host, Prolog-driven runtime settings,
Android-local execution and a stock API-to-KB end-to-end test remain integration
work. The Prolog module is shipped, not silently claimed to execute in Python.

## Agent workflow

Retrieve source evidence, persist a quote through the correct trust boundary,
retrieve historical context, calculate through `stock.money`, and evaluate the
candidate against current evidence. Keep research notes separate. Never invent
an authenticated feed, omit a blocker, convert a hypothetical result to an order,
retry an unknown-outcome mutation under a new ID, or claim a stored quote is live
without its timestamp/feed context.

## Install and test

Once the reviewed registry change is merged:

```sh
nix build github:lost-rob0t/zara-plugins#zara-stock-expert
python3 -m unittest discover -s plugins/zara-stock-expert/test -t plugins/zara-stock-expert/test
python3 scripts/validate-registry.py
nix flake check
```

The registry exposes the package and dependency-backed runtime library. It does
not install or enable itself in a running Zara instance. Dependencies are Python's
standard library and `langchain-core` supplied by Zara/the Nix package. Real-Zara
and SWI-Prolog tests are explicitly skipped when those runtimes are absent. Do
not count skips as a passed integration gate.

Arithmetic reference: https://docs.python.org/3/library/decimal.html

License: GPL-3.0-or-later. Tracking issue: #808.
