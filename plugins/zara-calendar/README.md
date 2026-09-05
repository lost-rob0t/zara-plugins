# zara-calendar

Provider-neutral calendar search, free/busy, conflict reasoning, scheduling suggestions, and explicit verified event mutations for Zara.

The public model keeps provider IDs and versions while preserving timezone, recurrence, attendee, and reminder data. Backends such as Google Calendar or CalDAV stay behind the adapter boundary; credentials never belong in tool output, fixtures, Git, or the Nix store.

## Tools

- `calendar.status`
- `calendar.search`
- `calendar.get`
- `calendar.free_busy`
- `calendar.conflicts`
- `calendar.suggest`
- `calendar.create`
- `calendar.update`
- `calendar.delete`

Search windows and result counts are bounded and require timezone-aware timestamps. Suggestions are explicitly read-only and never create an event.

Create/update/delete preserve provider acknowledgement and then inspect fresh provider state. Updates and deletes require an expected version; rejected or stale mutations never report success. Attendee changes occur only when the explicit patch includes `attendees`.

Without a configured provider backend the service reports `calendar-backend-not-configured` rather than fabricating data. Tests use a fake backend and require no account, network, GUI, or credentials. Zara Core remains responsible for normal tool authorization and approval policy.
