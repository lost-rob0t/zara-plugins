# zara-doordash

Provider-specific DoorDash commerce adapter for Zara.

## What it does

- `doordash.prepare` builds a bounded DoorDash consumer search handoff.
- `doordash.checkout` is **always Zara Core approval-gated**. In the default consumer mode it opens the DoorDash handoff through `browser.tab.open`; it does not claim payment or order submission succeeded.
- `doordash.preferences` reads learned contextual food/item patterns from `zara-memory`.
- After an approved handoff, the plugin can record a low-authority `selected` observation through `memory.preference.observe`. Preference learning never grants spending or checkout authority.

DoorDash's public developer surface does not provide an unrestricted consumer-cart checkout API. This plugin therefore separates the consumer handoff backend from future authorized Marketplace/partner integrations instead of fabricating an API.

## Configuration

```toml
[plugins.zara-doordash]
learning_enabled = true
preference_min_observations = 2
preference_limit = 10
max_url_chars = 2048
```

No credentials are stored in this plugin configuration.

## Verification

```sh
python3 -m unittest discover -s plugins/zara-doordash/test -t plugins/zara-doordash/test
python3 scripts/validate-registry.py
nix flake check
```
