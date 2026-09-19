# zara-emacs

Structured Emacs integration for Zara using `emacsclient` and fixed operation templates. It owns Emacs-specific semantics; it does not provide a general shell or arbitrary-Elisp tool.

## Operations

- `emacs.open_scratch`
- `emacs.open_file(path)` — absolute paths only, passed as an argv element.
- `emacs.open_buffer(name)` — data is encoded as an Elisp string inside a fixed template.
- `org_roam.open_daily(date=today)` — opens a daily note, then returns `post_open: {request: dictation, started: false}` for Zara Core to consume.
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

Configure `emacsclient`, `server_name`, `timeout_seconds`, `projects`, and `workflows` through Zara's plugin configuration. Project paths, workflow names, and private aliases remain user-owned configuration and are never committed as defaults or written into the Nix store.

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
