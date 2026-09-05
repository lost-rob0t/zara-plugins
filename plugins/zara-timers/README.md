# zara-timers

Reliable local countdown timers, wall-clock alarms, recurring reminders, and due-event primitives for Zara. Timing correctness does not depend on desktop, voice, calendar, network, or model conversational state.

Countdown timers use monotonic elapsed time while the process is live. Persisted countdown state stores remaining duration plus a wall-clock save point so restart recovery can account for downtime without persisting process-specific monotonic values. Alarms and recurring reminders require timezone-aware absolute timestamps; reminders also retain an explicit IANA timezone and bounded cadence.

State is deterministic schema-versioned JSON under `$XDG_STATE_HOME/zara/plugins/zara-timers/timers.json` (or `~/.local/state/...`) by default, written through an atomic replace. Mutable state therefore stays outside the Nix store. Corrupt or unsupported state fails closed instead of silently resetting timers.

## Missed events

The default `fire_once` policy emits one `fired` event when an overdue timer/alarm/reminder is next polled after downtime. A recurring reminder advances to the first future occurrence after that single catch-up event. The optional `skip` policy advances recurrence without emitting missed reminder events and marks missed one-shot alarms complete.

## Tools

- `timers.create`, `timers.alarm`, `timers.reminder`
- `timers.list`, `timers.get`
- `timers.pause`, `timers.resume`, `timers.cancel`
- `timers.poll_due`, `timers.drain_events`

Stable IDs support reliable lookup and cancellation. `poll_due` advances timing state and returns only newly-fired events; `drain_events` exposes queued `fired`/`cancelled` events for other plugins to consume. Presentation integrations may react to those events but never participate in scheduling correctness.

Tests use a deterministic fake clock and temporary state only: no sleeping, network, GUI, credentials, or external services.
