# zara-desktop

Structured Linux desktop operations for Zara without turning desktop control into arbitrary shell execution.

## Safety model

Application launch is alias-based. Operators configure a bounded argv list for each allowed application; Zara only selects the alias and cannot supply command strings or extra argv. Clipboard and screenshot payloads are byte-bounded. Unsupported platform features return explicit `unavailable` results instead of fabricated success. The plugin does not expose synthetic keyboard/mouse input or an arbitrary command/eval surface.

## Configuration

```toml
[plugins.zara-desktop.applications]
browser = ["brave", "--new-window"]
files = ["thunar"]
```

Mutable configuration remains in the operator's normal Zara/XDG configuration, never in the Nix store.

## Tools

- `desktop.status`
- `desktop.launch(application)`
- `desktop.clipboard_read`
- `desktop.clipboard_write(text)`
- `desktop.screenshot`
- `desktop.windows`
- `desktop.workspaces`

The initial Linux adapter supports configured app launch and opportunistic Wayland clipboard/screenshot backends (`wl-paste`, `wl-copy`, `grim`). Window/workspace operations intentionally report unavailable until a structured compositor adapter is configured; they do not fall back to shell snippets.

## Events

The public domain reserves structured desktop event names such as `window.created`, `window.closed`, `window.focused`, `workspace.changed`, `clipboard.changed`, `notification.received`, and `audio.device.changed`. Event subscription will use backend-native streams rather than high-frequency polling when an adapter provides them.

## Verification

Tests use fake backends and require no GUI, network, credentials, or desktop session. The repository compatibility gate additionally loads the packaged service against the pinned supported Zara API.
