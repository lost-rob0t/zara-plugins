# scrot screenshot context

`zara-desktop` supports `grim` and `scrot` as bounded screenshot backends. The screenshot-to-model hook is disabled by default.

```toml
[plugins.zara-desktop]
screenshot_backend = "scrot" # auto | grim | scrot
screenshot_context_hook_enabled = true
screenshot_context_hook_priority = -500
```

With `scrot`, Zara executes exactly the equivalent of:

```text
scrot --silent --file -
```

through `subprocess` argv with `shell=False`. PNG output is read from stdout, bounded by the plugin screenshot size limit, and added to the current user message as a multimodal image block only when the hook is enabled. The explicit `desktop.screenshot` tool uses the same backend.

`auto` prefers `grim` when available and otherwise uses `scrot`. Selecting `scrot` explicitly does not silently fall through to a different backend.

Ordinary chat does not capture the desktop when the hook is disabled. The hook registration participates in Zara's canonical before/around/after ordering and can be disabled through runtime hook controls without uninstalling the plugin.
