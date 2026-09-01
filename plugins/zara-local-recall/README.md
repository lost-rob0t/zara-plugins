# Zara Local Recall

`zara-local-recall` is a Zarathushtra service plugin that connects Zara to
[Local Recall](https://github.com/lost-rob0t/local-recall) — local-first,
encrypted desktop activity recall. Zara can ask what you were doing, search
your captured activity, read daemon status, and request a policy-gated
explanation of your current desktop context.

Local Recall stays the sole authority for capture, redaction, retrieval, and
provider routing. The plugin is an owner-authenticated client: it talks only
to the daemon over the owner-only local IPC boundary and never reads
screenshots, storage, or key material.

## Tools

| Tool | Purpose |
| --- | --- |
| `local_recall_status` | Content-free daemon status (capture state, privacy mode) |
| `local_recall_ask` | Cited natural-language answers; the question must include one time scope (`today`, `yesterday`, `saturday`, `last 3 hours`, `2026-08-31`) |
| `local_recall_search` | Bounded search between two explicit ISO-8601 timestamps |
| `local_recall_explain_screen` | Explain the current desktop context from recent redacted captures through the `zara-visual-context-v1` protocol; local vision only, never a silent remote fallback |

## Install

From this repository checkout:

```sh
python3 plugins/zara-local-recall/tools/zara-local-recall install

# Or via Nix
nix run github:lost-rob0t/zara-plugins#zara-local-recall -- install
```

The installer places the Zara discovery entry at
`~/.zarathushtra/plugins/zara_local_recall.py` and the plugin library at
`$XDG_CONFIG_HOME/zarathushtra/plugins/zara-local-recall/lib/`. It is
idempotent; re-running refreshes the library without touching your Zara
configuration.

## Requirements

- A running Local Recall daemon (`local-recall daemon`) with the CLI on
  `PATH`. The plugin fails closed with a sanitized reason when the daemon is
  unreachable; queries return `unavailable: ...` instead of hanging.
- Same-user session: the daemon's credentials live under your
  `XDG_RUNTIME_DIR` and are usable only by your UID.
- Optional: `langchain_core` in Zara's runtime for tool registration (the
  service plugin itself has no Python dependencies).

## Configuration

Plugin-owned settings live in Zara's `config.toml`:

```toml
[plugins.zara-local-recall]
enabled = true                    # disable without uninstalling
visual_selector = "recent"        # "current" or "recent"
visual_maximum_records = 3        # 1..8 records decrypted per explanation
visual_timeout_seconds = 8.0      # bounded deadline for visual-context requests
cli_timeout_seconds = 15.0        # bounded deadline for CLI bridge calls
```

## Privacy model

- Every frame the daemon explains was already deterministically redacted
  before storage; the plugin receives bounded explanation text only.
- Screen explanation requires Local Recall's capture to be active; privacy
  mode, session lock, and non-active capture return stable reason codes
  (`privacy-mode`, `capture-not-active`, `missing-context`).
- Remote analysis is never requested: the plugin always sends
  `remote_authorization=absent`, so `provider_class` is always `local`.
- All timeouts and response-size bounds are enforced in the plugin;
  daemon responses are closed-schema JSON.
