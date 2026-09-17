# zara-calendar

Provider-neutral calendar search, free/busy, conflict reasoning, scheduling suggestions, and explicit verified event mutations for Zara.

The public model keeps provider IDs and versions while preserving timezone, recurrence, attendee, and reminder data. Google Calendar API and CalDAV stay behind the same `CalendarDomain` boundary; credentials never belong in tool input/output, fixtures, Git, logs, or the Nix store.

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

## Provider selection

A fresh installation has no provider configured and reports `calendar-backend-not-configured`. Set exactly one provider. If Google and CalDAV configuration are both present, set `ZARA_CALENDAR_BACKEND=google` or `ZARA_CALENDAR_BACKEND=caldav`; otherwise startup fails closed rather than guessing which principal owns a request.

### Google Calendar API

The Google backend is bound to one server-owned OAuth principal. Configure:

```text
ZARA_CALENDAR_BACKEND=google
ZARA_CALENDAR_GOOGLE_ACCESS_TOKEN=...
ZARA_CALENDAR_GOOGLE_REFRESH_TOKEN=...
ZARA_CALENDAR_GOOGLE_CLIENT_ID=...
ZARA_CALENDAR_GOOGLE_CLIENT_SECRET=...
ZARA_CALENDAR_GOOGLE_CALENDAR_ID=primary
```

`ZARA_CALENDAR_BACKEND` is optional when only Google variables are present. OAuth secrets never appear in calendar tool arguments. The adapter follows bounded pagination, performs one access-token refresh after a 401, uses optimistic version evidence for mutations, and leaves independent post-write verification to `CalendarDomain`.

### CalDAV

The CalDAV backend is bound to one HTTPS calendar collection and one logical calendar ID. It supports either HTTP Basic credentials or a Bearer token.

Basic authentication:

```text
ZARA_CALENDAR_BACKEND=caldav
ZARA_CALENDAR_CALDAV_URL=https://calendar.example.test/dav/calendars/me/work/
ZARA_CALENDAR_CALDAV_CALENDAR_ID=work
ZARA_CALENDAR_CALDAV_USERNAME=me
ZARA_CALENDAR_CALDAV_PASSWORD=...
```

Bearer authentication:

```text
ZARA_CALENDAR_BACKEND=caldav
ZARA_CALENDAR_CALDAV_URL=https://calendar.example.test/dav/calendars/me/work/
ZARA_CALENDAR_CALDAV_CALENDAR_ID=work
ZARA_CALENDAR_CALDAV_BEARER_TOKEN=...
```

`ZARA_CALENDAR_BACKEND` is optional when only CalDAV variables are present. Callers cannot replace the configured collection URL, origin, credentials, or logical calendar ID.

The adapter uses a bounded `calendar-query` REPORT with `DAV:getetag` and `calendar-data`, requests recurrence expansion for the requested window, and uses the server's strong ETag as Zara's provider version. Creates use conditional PUT with `If-None-Match: *`; updates/deletes use `If-Match`. Provider 409/412 responses are surfaced as stale-version failures. Redirects are refused so an Authorization header cannot be carried to another origin.

The current normalized domain supports timed timezone-aware VEVENTs. All-day and floating-time events are rejected instead of being silently coerced. DISPLAY VALARMs map to Zara popup reminders; transparent VEVENTs do not contribute busy intervals.

## Verification boundary

A provider acknowledgement is never enough for `verified=true`. `CalendarDomain` independently reads the resulting event after create/update and checks absence after delete. If observed state/version differs from the requested state, the tool returns verification failure even when the provider accepted the mutation.

Tests use deterministic fake transports/backends and require no live account, network, GUI, or credentials. Zara Core remains responsible for normal tool authorization and approval policy. Android device-calendar intents are a separate Zara Core capability and do not receive these provider credentials.
