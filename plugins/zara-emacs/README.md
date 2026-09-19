# zara-emacs

Structured Emacs integration for Zara using `emacsclient` and fixed operation templates. It owns Emacs-specific semantics; it does not provide a general shell or arbitrary-Elisp tool.

## Operations

- `emacs.open_scratch`
- `emacs.open_file(path)` — absolute paths only, passed as an argv element.
- `emacs.open_buffer(name)` — data is encoded as an Elisp string inside a fixed template.
- `org_roam.open_daily(date=today)` — opens a daily note, then returns `post_open: {request: dictation, started: false}` for Zara Core to consume.
- `org_ql.shared_memory(limit=100)` — returns bounded active shared-memory assertions from the full Org graph.
- `org_ql.inventory(limit=100)` — returns bounded inventory/item/location/food/event rows from structured Org properties.
- `inventory.unresolved(limit=100)` — lists daily inventory events that do not yet reference a stable item Org ID.
- `inventory.materialize_item(...)` — resolves an item key to an existing item node or creates a stable Org-roam inventory-item node.
- `inventory.record_event(...)` — appends ordered/receive/buy/putaway/move/open/consume/waste/return/adjust events to the selected Org-roam daily page.
- `org_memory.append_shared(subject, value, author, source, supersedes="")` — appends a fresh provenance-bearing Org-roam memory node and optionally supersedes a prior assertion.
- `magit.open_project(project_id)` — resolves only configured aliases to absolute paths.
- `emacs.context` — bounded server-reported buffer/file/project context.

## Configuration

Configure `emacsclient`, `server_name`, `timeout_seconds`, `notes_root` (default `~/Documents/Notes/org`), and a `projects` alias mapping through Zara's plugin configuration. Project paths and private aliases remain user-owned configuration and are never committed as defaults or written into the Nix store.

The plugin intentionally accepts a command *name* for `emacsclient`, not a shell command/path fragment. Every process call uses an argv vector with `shell=false`; tool parameters never become executable Elisp structure. Operations requiring Elisp use fixed templates and encode user/project data as string literals.

## Dictation boundary

The plugin never opens a microphone, starts a recorder, or claims dictation is active. A successfully acknowledged daily-note open carries a distinct post-open request for Zara Core's canonical hook/voice runtime. Until Core consumes that seam, the result truthfully reports `started: false`.

## Failure semantics

A missing client, unavailable server, timeout, nonzero Emacs result, unknown project alias, or invalid argument fails explicitly. Successful results mean the configured Emacs boundary acknowledged the requested editor action; they do not imply unrelated post-actions succeeded.

## Verification

```sh
python3 scripts/validate-registry.py
python3 -m unittest discover -s plugins/zara-emacs/test -t plugins/zara-emacs/test
nix flake check
```

Tests use a fake process runner and require no GUI, Emacs server, network, microphone, or private project data.


## Org knowledge graph

The Org tools deliberately use the same human-readable graph owned by the gpt-todos/full-notes workflow. They do not create a Zara-only database.

Shared-memory writes are append/supersede operations. The plugin creates a fresh Org ID, records KIND=memory, MEMORY_SCOPE=shared, subject/value, revision, author, source, timestamp, and optional SUPERSEDES, then asks Org-roam to refresh and invokes the existing gpt-todos sync hook when available. A supplied superseded ID must exist and have the same subject.

All user strings are bounded single-line data encoded into fixed Elisp templates. No tool accepts arbitrary Elisp or shell.


### Daily -> inventory workflow

A purchase can be captured immediately with an ITEM_KEY and no ITEM_ID.
`inventory.unresolved` finds those historical daily events.
`inventory.materialize_item` creates the stable item node once, keyed by
ITEM_KEY, or returns the existing node if it is already materialized. Historical
events are not rewritten; future events can carry the returned Org ID. Manual
`adjust` events additionally require `adjustment=add|remove`; Zara never guesses
the sign of an inventory correction.
