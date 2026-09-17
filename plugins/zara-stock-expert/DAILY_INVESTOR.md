# Daily investor automation

`stock.daily_investor` is the unattended research entry point for the stock expert.
It is intentionally implemented inside the Zara stock plugin rather than as a
ChatGPT automation.

## Authorization model

The bundled Prolog policy is authoritative for this capability:

```prolog
stock_daily_investor_authorized(research).
```

The same policy explicitly excludes arbitrary instruments, broker orders, and
live execution. Python requires a unique SWI-Prolog proof of the research policy
before any daily network or KB work starts. If Prolog is disabled, unavailable,
or does not return a unique proof, the run fails closed.

`stock.daily_investor` is deliberately not marked `zara_requires_approval` because
it is the pre-authorized unattended path. Interactive write tools such as
`stock.fetch_quote`, `stock.neural_train`, `stock.neural_forecast`,
`stock.report_quote`, and `stock.remember_note` retain their normal host approval
metadata.

This authorization covers research I/O only. It is not authorization to submit,
modify, cancel, or route brokerage orders.

## Instrument authority

The tool accepts no instrument argument. It can only operate on the instruments
already present under the operator-controlled market-data mapping:

```toml
[plugins.zara-stock-expert.market_data.instruments."XNAS:EXAMPLE"]
symbol = "EXAMPLE"
currency = "USD"
```

The implementation caps unattended runs at 64 configured instruments. A model or
prompt cannot expand the allowlist during the run.

## One run

For each configured instrument, one invocation:

1. proves the research-only Prolog policy;
2. fetches and persists configured provider evidence;
3. reads a bounded recent KB history;
4. lists up to two registered neural models;
5. when neural execution is enabled, runs and persists forecasts for those models;
6. writes a compact `daily-investor` research note recording evidence IDs,
   forecast IDs, and per-stage errors.

Failures are isolated per instrument and stage so one stale model or provider
failure does not erase results for the remaining allowlisted instruments.
Forecasts remain `execution_eligible=false` and the run result repeats
`live_execution=false`.

The daily path does not invent account balances or risk limits. Exact-money
position sizing continues to require explicit account/risk inputs through
`stock.money` / `stock.evaluate`.

## Scheduling in Zara

The stock plugin owns the policy and the research cycle, not a second timer loop.
Use Zara's recurring-task facility to invoke the zero-argument tool once per day.
For the current Agent Mode scheduler, the recurring instruction should be narrow,
for example:

```text
Call stock.daily_investor exactly once. Summarize its persisted evidence,
forecast uncertainty, and errors. Do not place or propose a broker order.
```

Set that task to a 1440-minute interval, or use the dedicated scheduled-task
system when it is available in the host. Scheduling the call does not weaken the
Prolog authorization boundary.

## Required runtime

- `[plugins.zara-stock-expert].prolog_enabled = true`
- at least one configured `market_data.instruments` entry
- `zara-expert` plus SWI-Prolog
- provider credentials/configuration required by the selected market adapter
- optional neural runner for forecast execution; stored models can still be
  listed when neural execution is disabled

The existing provider caveats still apply. The Alpha Vantage GLOBAL_QUOTE adapter
in this draft stores day-precision historical observations with unknown adjustment
semantics; it is not promoted to realtime market evidence by the daily workflow.
