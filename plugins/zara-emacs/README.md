# zara-emacs

Structured Emacs integration for Zara using `emacsclient` and fixed operation templates. It owns Emacs-specific semantics; it does not provide a general shell or arbitrary-Elisp tool.

## Operations

- `emacs.command_catalog` — lists configuration-owned stable action IDs and their exact interactive command symbols.
- `emacs.invoke_command(action_id)` — invokes only a configured action ID through `call-interactively`; callers cannot submit raw Elisp or raw command symbols.
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
- `emacs.open_dashboard` — opens the typed dotfiles AI dashboard through a fixed Elisp template.
- `emacs.open_zara_chat` — opens the native Zara Emacs client through a fixed template.
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

Configure `emacsclient`, `server_name`, `timeout_seconds`, `notes_root`, `projects`, `commands`, and optional `workflows` through Zara's plugin configuration. `notes_root` remains the configured Org knowledge surface; project paths, workflow names, roots, and private aliases remain user-owned configuration and are never written into the Nix store.

The plugin intentionally accepts a command *name* for `emacsclient`, not a shell command/path fragment. Every process call uses an argv vector with `shell=false`; tool parameters never become executable Elisp structure. Operations requiring Elisp use fixed templates and encode user/project data as string literals.

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


## Voice control

Voice is an input adapter, not a separate execution path. Speech recognition resolves an utterance to a stable `action_id` from `emacs.command_catalog`, then calls `emacs.invoke_command`. Deterministic phrases should win first; expert-assisted semantic resolution may propose an action ID, but the final invocation still passes through the configured capability catalog.

Examples:

- "split window right" -> `window.split-right`
- "other window" -> `window.other`

This keeps voice, chat, keyboard macros, and future agents on one auditable action protocol.

## Emacs expert KB

The plugin ships a Nix-built exporter under `expert/`. It runs a pinned Emacs build in batch mode and emits Prolog facts from Emacs' self-documenting runtime: version, interactive commands, functions, variables, documentation strings, source/library provenance, and active key bindings. The generated KB is data-only and is intended to be loaded through Zara's existing expert host/protocol.

The expert answers discovery questions such as "what command splits the window right?" and returns canonical symbols/action candidates. It never executes Elisp; execution remains the responsibility of `emacs.invoke_command`.
