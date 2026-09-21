# zara-emacs

Deep native Emacs integration for Zara using `emacsclient` only as the transport to the versioned `ZARA-EMACS/1` semantic bridge in Zara's native `emacs/zara.el` package. Editor requests select closed typed operations and carry arguments as base64 JSON; tool/model text never becomes executable Elisp.

## Operations

## Org TODO / roam adapter ownership

The public tools above never accept raw Elisp. They invoke fixed `command.invoke` adapter IDs over `ZARA-EMACS/1`; an operator configuration must register those adapters inside the running Emacs. If an adapter is absent, the operation fails explicitly.

Org remains the mutable source of truth. `org_todo.snapshot` may produce a Prolog fact projection for deterministic expert reasoning, but that projection is derived/read-only and must never become a competing task database. Task mutation returns to Org through Emacs, then the projection is regenerated.


- `emacs.open_scratch`
- `emacs.open_file(path)` — absolute paths only, executed by the native bridge.
- `emacs.open_buffer(name)` — compatibility open/switch through the native bridge.
- `emacs.session_describe` — live bridge version, Emacs session, and capability discovery.
- `emacs.buffers(limit=100)` / `emacs.buffer_context(buffer_id="")` — opaque live buffer identities, modes, point/mark, project, read-only/dirty state, and modification ticks.
- `emacs.read_buffer(buffer_id, start, end)` — bounded buffer reads.
- `emacs.preview_edit(...)` / `emacs.apply_edit(edit_id)` / `emacs.cancel_edit(edit_id)` / `emacs.edit_status(edit_id)` — revision-safe edit receipts; apply rechecks the captured modification tick and leaves edits in normal Emacs undo history.
- `emacs.save_buffer(buffer_id)` — explicit save; edit application never saves implicitly.
- `emacs.windows`, `emacs.select_window`, `emacs.split_window`, `emacs.delete_window` — selected-frame native window operations using opaque IDs.
- `emacs.commands`, `emacs.describe_command`, `emacs.where_is`, `emacs.key_lookup` — live command/key introspection against the running Emacs state.
- `org_roam.open_daily(date=today)` — opens a daily note, then returns `post_open: {request: dictation, started: false}` for Zara Core to consume.
- `org_todo.list(state=active, limit=100)` — lists canonical Org tasks through a trusted Emacs adapter.
- `org_todo.capture(title, scheduled="")` — appends a canonical Org task with an optional ISO date/time.
- `org_todo.state(todo_id, state)` — changes one task by stable Org ID; accepted states are `TODO`, `NEXT`, `WAIT`, `DONE`, and `CANCELLED`.
- `org_todo.snapshot()` — refreshes the derived Prolog projection of canonical Org task state.
- `org_roam.search(query, limit=50)` — performs bounded node search through the operator-owned Org-roam adapter.
- `org_ql.shared_memory(limit=100)` — returns bounded active shared-memory assertions from the full Org graph.
- `org_ql.inventory(limit=100)` — returns bounded inventory/item/location/food/event rows from structured Org properties.
- `inventory.unresolved(limit=100)` — lists daily inventory events that do not yet reference a stable item Org ID.
- `inventory.materialize_item(...)` — resolves an item key to an existing item node or creates a stable Org-roam inventory-item node.
- `inventory.record_event(...)` — appends ordered/receive/buy/putaway/move/open/consume/waste/return/adjust events to the selected Org-roam daily page.
- `org_memory.append_shared(subject, value, author, source, supersedes="")` — appends a fresh provenance-bearing Org-roam memory node and optionally supersedes a prior assertion.
- `magit.open_project(project_id)` — resolves only configured aliases to absolute paths.
- `emacs.open_dashboard` — opens the typed dotfiles AI dashboard through the native bridge.
- `emacs.open_zara_chat` — opens the native Zara Emacs client through the native bridge.
- `emacs.run_workflow(workflow_id)` — runs a named, configuration-owned sequence of reviewed operations.
- `emacs.context` — bounded server-reported buffer/file/project context.

## Named workflows

Workflows are operator-owned configuration. The model supplies only a workflow id; it cannot provide an ad-hoc executable step list.

Supported workflow steps are:

- `open_scratch`
- `open_file`
- `open_buffer`
- `open_daily`
- `open_magit`
- `open_dashboard`
- `open_zara_chat`

A workflow contains 1–32 steps. File paths must be absolute, Magit steps may reference only configured project aliases, daily dates are `today` or ISO `YYYY-MM-DD`, and fixed operations reject arguments.

Example plugin configuration:

```toml
emacsclient = "emacsclient"
server_name = "server"
timeout_seconds = 10
notes_root = "/home/me/notes/org"

[projects]
zara = "/home/me/src/zara"

[workflows]
coding = [
  { operation = "open_dashboard" },
  { operation = "open_magit", argument = "zara" },
  { operation = "open_zara_chat" },
]
```

This gives Zara a compact operation such as “run my coding workflow” without turning editor orchestration into arbitrary shell or arbitrary Elisp.

## Configuration

Configure `emacsclient`, `server_name`, `timeout_seconds`, `notes_root`, `projects`, and optional `workflows` through Zara's plugin configuration. `notes_root` remains the configured Org knowledge surface; project paths, workflow names, roots, and private aliases remain user-owned configuration and are never written into the Nix store.

The plugin intentionally accepts a command *name* for `emacsclient`, not a shell command/path fragment. Every process call uses an argv vector with `shell=false`. Editor-control operations call one fixed Lisp entrypoint, `zara-bridge-call`, with base64 JSON and require the exact `ZARA-EMACS/1` response. The native package owns operation dispatch and refuses unknown operations. The existing Org knowledge/inventory functions remain bounded fixed templates because they are data/knowledge operations rather than generic editor control.

## Native bridge requirement

The configured Emacs server must load a Zara native package that reports the same `ZARA-EMACS/1` bridge version. A missing package, stale bridge version, malformed receipt, mismatched operation, or bridge-side failure is explicit. There is no fallback to arbitrary or model-constructed Elisp.

## Dictation boundary

The plugin never opens a microphone, starts a recorder, or claims dictation is active. A successfully acknowledged daily-note open carries a distinct post-open request for Zara Core's canonical hook/voice runtime. Until Core consumes that seam, the result truthfully reports `started: false`.

## Failure semantics

A missing client, unavailable server, timeout, nonzero Emacs result, unknown project/workflow alias, unsafe workflow definition, or invalid argument fails explicitly. Workflow execution reports the exact failing step and stops immediately. Successful results mean the configured Emacs boundary acknowledged the requested editor action; they do not imply unrelated post-actions succeeded.

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
