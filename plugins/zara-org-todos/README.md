# zara-org-todos

Org-mode todo backend for Zara. Git synchronization is optional.

Org files are the authoritative task store. The plugin works as a completely local Org-mode backend without Git, a Git executable, a remote repository, or a network connection. Users who want remote synchronization can opt into the bundled Git transport and provide their own repository.

The optional Git sync engine preserves the conflict-safe behavior ported from `lost-rob0t/dotfiles` `scripts/gpt-todos-sync` at commit `7b88a3c2ddef7f3fffc09fd049476e06cf13d93a`. That source is an implementation reference only; the public plugin does not default to or require the author's todo repository.

## What it does

- Captures new tasks as Org TODO headings in `inbox.org` with stable `:ID:` properties.
- Lists and searches TODO/STRT/WAIT/HOLD/IDEA/LOOP tasks recursively.
- Edits, completes, reopens, and schedules tasks by stable ID.
- Works directly against the configured Org agenda with Git disabled.
- Optionally synchronizes mutations through a Git repository when `git_sync = true`.
- Optionally runs periodic Git sync through Zara's managed plugin worker.
- Exposes explicit sync and backend-status tools.
- When Git is enabled, uses Git blob identity and the durable checkout `HEAD` as the sync baseline.
- When Git is enabled, fails closed on concurrent local/remote edits, remote deletions, dirty durable agenda state, and rebase conflicts.
- Preserves task-aware Git commit messages for TODO/DONE and checkbox state transitions.

The Zara tools are currently prefixed `org_todos_*`. Zara core issue `lost-rob0t/zara#246` tracks disabling/replacing the built-in todo intent/tool surface so an external todo backend can become authoritative without two stores competing.

## Defaults

- Live Org agenda: `~/Documents/Notes/org/agenda`
- Git synchronization: **disabled**
- Periodic Git synchronization: **disabled**
- Git remote: **none**
- Optional durable Git checkout: `$XDG_DATA_HOME/zarathushtra/org-todos-git` (normally `~/.local/share/zarathushtra/org-todos-git`)
- Interval when periodic Git sync is enabled: 300 seconds
- Sync timeout: 120 seconds

In the default configuration, todo mutations only modify Org files. No Git command is spawned.

## Optional Git synchronization

Git is an optional transport, not the todo backend. To enable it, configure a repository you control:

```toml
[plugins.zara-org-todos]
org_dir = "~/Documents/Notes/org/agenda"
git_sync = true
remote = "git@github.com:YOUR_USER/YOUR_TODO_REPO.git"
repo_dir = "~/.local/share/zarathushtra/org-todos-git"
auto_sync = true
interval_seconds = 300
```

`remote` is required when `git_sync = true`. There is deliberately no built-in remote repository default.

Plugin configuration accepts `org_dir`, `git_sync`, `repo_dir`, `remote`, `auto_sync`, `interval_seconds`, and `timeout_seconds`.

Environment variables override plugin configuration:

- `ZARA_ORG_TODOS_ORG_DIR`
- `ZARA_ORG_TODOS_GIT_SYNC`
- `ZARA_ORG_TODOS_REPO_DIR`
- `ZARA_ORG_TODOS_REMOTE`
- `ZARA_ORG_TODOS_AUTO_SYNC`
- `ZARA_ORG_TODOS_INTERVAL`
- `ZARA_ORG_TODOS_TIMEOUT`

`auto_sync = true` requires `git_sync = true`. The minimum periodic interval is 60 seconds.

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

With Git disabled, `org_todos_sync` reports that synchronization is disabled and all CRUD/scheduling tools continue to work locally. With Git enabled, mutations synchronize before and after the local change so stale remotes cannot silently overwrite task state.

## Install

```sh
python3 plugins/zara-org-todos/tools/zara-org-todos install
```

or:

```sh
nix run github:lost-rob0t/zara-plugins#zara-org-todos -- install
```

The installer places the service implementation under `$XDG_CONFIG_HOME/zarathushtra/plugins/zara-org-todos/` and the discovery entry at `~/.zarathushtra/plugins/zara_org_todos.py`.

## Runtime requirements

Org-only mode uses the Python standard library plus Zara's plugin runtime and does not require Git.

When `git_sync = true`, the optional sync engine additionally expects `bash`, `git`, `flock`, `find`, `awk`, `sort`, `realpath`, and standard core utilities. Git operations are non-interactive and SSH defaults to batch mode.

## Verification

```sh
python3 scripts/validate-registry.py
python3 -m unittest discover -s plugins/zara-org-todos/test -t plugins/zara-org-todos/test
nix flake check
```

The Git integration test uses only temporary local repositories and performs no network access.
