# zara-healthcheck

Passive, read-only health monitoring for Zara. The plugin normalizes bounded probe observations, retains short history, applies hysteresis to reduce flapping, emits deduplicated state-change events, and exports structured evidence for expert consumers such as `zara-sysadmin`.

The monitor does **not** remediate anything. Probes are adapters for read-only observations such as CPU/memory/disk pressure, process/service state, HTTP endpoint reachability, DNS latency, or other bounded signals. A failed or malformed probe becomes `unknown`; exception messages are not copied into public evidence by default.

## Tools

- `health.status`
- `health.poll`
- `health.state`
- `health.history`
- `health.drain_events`
- `health.export_facts`

`health.poll` performs one explicit probe cycle. There is no mandatory daemon or watcher. Callers may schedule polling externally. Current state changes only after the configured hysteresis threshold is met; repeated samples in the same accepted state do not emit duplicate events.

History, probe count, and evidence bytes are bounded. Facts preserve `healthy`, `degraded`, `unhealthy`, and `unknown` instead of collapsing uncertainty into success. The fact surface is intentionally structured so an expert system can reason over evidence while keeping monitoring separate from any privileged remediation path.

An install with no configured probes reports `health-probes-not-configured`. Tests use deterministic fake probes/clocks and require no network, host services, privileges, or credentials. Zara Core remains authoritative for normal tool authorization and approval policy.
