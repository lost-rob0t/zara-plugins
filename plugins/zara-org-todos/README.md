# zara-org-todos

Org-mode todo backend for Zara with durable Git synchronization.

This plugin makes a recursive Org agenda the task store and synchronizes it with the same `gpt-todos` repository workflow used by the current dotfiles sync helper. Its sync engine is ported from `lost-rob0t/dotfiles` `scripts/gpt-todos-sync` at commit `7b88a3c2ddef7f3fffc09fd049476e06cf13d93a` (current `master` when this plugin was created).

## What it does

- Captures new tasks as Org TODO headings in `inbox.org` with stable `:ID:` properties.
- Lists and searches TODO/STRT/WAIT/HOLD/IDEA/LOOP tasks recursively.
- Edits, completes, reopens, and schedules tasks by stable ID.
- Synchronizes each mutation through the save-safe `--file` path.
- Runs a periodic full sync through Zara's managed plugin worker.
- Exposes explicit sync and backend-status tools.
- Uses Git blob identity and the durable checkout `HEAD` as the sync baseline.
- Fails closed on concurrent local/remote edits, remote deletions, dirty durable agenda state, and rebase conflicts.
- Preserves task-aware Git commit messages for TODO/DONE and checkbox state transitions.

The Zara tools are currently prefixed `org_todos_*`. Zara core issue `lost-rob0t/zara#246` tracks disabling/replacing the built-in todo intents and tools so this plugin can be selected as the authoritative natural-language todo backend without two stores competing.

## Defaults

- Durable repo: `~/Documents/gpt-todos`
- Live Org agenda: `~/Documents/Notes/org/agenda`
- Remote: `git@github.com:lost-rob0t/gpt-todos.git`
- Periodic sync: enabled
- Interval: 300 seconds
- Sync timeout: 120 seconds

Plugin configuration accepts `repo_dir`, `org_dir`, `remote`, `auto_sync`, `interval_seconds`, and `timeout_seconds`.

Environment variables override plugin configuration:

- `ZARA_ORG_TODOS_REPO_DIR`
- `ZARA_ORG_TODOS_ORG_DIR`
- `ZARA_ORG_TODOS_REMOTE`
- `ZARA_ORG_TODOS_AUTO_SYNC`
- `ZARA_ORG_TODOS_INTERVAL`
- `ZARA_ORG_TODOS_TIMEOUT`

The minimum periodic interval is 60 seconds.

## Tools

- `org_todos_list`
- `org_todos_add`
- `org_todos_edit`
- `org_todos_complete`
- `org_todos_reopen`
- `org_todos_search`
- `org_todos_schedule`
- `org_todos_sync`
- `org_todos_status`

Task mutations are written locally before synchronization. If a remote conflict occurs, the local Org edit remains intact and sync reports the conflict instead of overwriting either side.

## Install

```sh
python3 plugins/zara-org-todos/tools/zara-org-todos install
```

or:

```sh
nix run github:lost-rob0t/zara-plugins#zara-org-todos -- install
```

The installer places the service implementation and bundled sync engine under `$XDG_CONFIG_HOME/zarathushtra/plugins/zara-org-todos/` and the discovery entry at `~/.zarathushtra/plugins/zara_org_todos.py`.

## Runtime requirements

The sync engine expects `bash`, `git`, `flock`, `find`, `awk`, `sort`, `realpath`, and standard core utilities. Git operations are non-interactive and SSH defaults to batch mode.

## Verification

```sh
python3 scripts/validate-registry.py
python3 -m unittest discover -s plugins/zara-org-todos/test -t plugins/zara-org-todos/test
nix flake check
```

The integration test uses only temporary local Git repositories and performs no network access.
