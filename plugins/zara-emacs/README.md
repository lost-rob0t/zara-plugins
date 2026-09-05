# zara-emacs

Structured Emacs integration for Zara using `emacsclient` and fixed operation templates. It owns Emacs-specific semantics; it does not provide a general shell or arbitrary-Elisp tool.

## Operations

- `emacs.open_scratch`
- `emacs.open_file(path)` — absolute paths only, passed as an argv element.
- `emacs.open_buffer(name)` — data is encoded as an Elisp string inside a fixed template.
- `org_roam.open_daily(date=today)` — opens a daily note, then returns `post_open: {request: dictation, started: false}` for Zara Core to consume.
- `magit.open_project(project_id)` — resolves only configured aliases to absolute paths.
- `emacs.context` — bounded server-reported buffer/file/project context.

## Configuration

Configure `emacsclient`, `server_name`, `timeout_seconds`, and a `projects` alias mapping through Zara's plugin configuration. Project paths and private aliases remain user-owned configuration and are never committed as defaults or written into the Nix store.

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
