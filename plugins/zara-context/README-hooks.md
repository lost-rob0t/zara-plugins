# Linux system-context hook

`zara-context` can contribute bounded Linux session facts to Zara's ordered agent-loop context pipeline.

The hook is opt-in:

```toml
[plugins.zara-context]
system_context_hook_enabled = true
system_context_hook_priority = -1000
```

The plugin registers one `before` advice callback through Zara's canonical plugin runtime. The priority participates in the same deterministic ordering as every other agent-loop hook. Zara's hook controls can disable the registration at runtime without uninstalling the plugin.

The provider deliberately reads only an allow-list of non-secret system/session fields: OS, kernel, architecture, `XDG_SESSION_TYPE`, `XDG_CURRENT_DESKTOP`, `DESKTOP_SESSION`, `WAYLAND_DISPLAY`, and `DISPLAY`. It does not dump the environment, HOME, credentials, clipboard contents, process lists, or arbitrary files.

If the shared Zara context hook API is unavailable, the hook cannot inject context; the normal `context.current` and `context.system` tools remain separate explicit operations.
