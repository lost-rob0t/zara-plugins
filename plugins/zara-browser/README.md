# zara-browser

Persistent, backend-neutral browser-session tools for Zara.

The plugin owns structured browser state and actions, not a second assistant/runtime. A backend adapter is responsible for attaching to a real browser. With no adapter configured the published plugin fails honestly with `browser-backend-not-configured`; it never pretends a browser action succeeded.

## Surface

- `browser.status`
- `browser.tab.open`, `browser.tab.close`, `browser.tab.switch`
- `browser.navigate`, `browser.reload`, `browser.back`, `browser.forward`
- `browser.extract`
- `browser.click`, `browser.type`, `browser.select`
- `browser.screenshot`
- `browser.download`

Session/tab state persists for the lifetime of the Zara service plugin instance. Backend adapters may additionally implement named/persistent browser profiles without changing the public tool schema.

## Safety

URLs are bounded HTTP(S) URLs with no userinfo. Selectors and typed values are bounded. Text extraction and screenshots have hard payload limits. Normal extraction never includes cookies or credential material. Typing never implicitly submits a form. Downloads accept only safe relative destinations for the backend's configured download root. Every action must return backend-observed evidence; unavailable features return an explicit unavailable/error state.

Zara Core remains responsible for canonical tool authorization and approval policy. This plugin does not auto-approve browser actions or expose arbitrary JavaScript/eval/shell execution.

## Backends

`BrowserSession` is the stable adapter boundary. The repository includes a deterministic in-memory backend for tests. Production browser drivers should implement the same structured operations and enforce their own connection/session timeouts. No GUI, browser, network, cookie store, or credential is required by the test suite.

## Verification

```sh
python3 scripts/validate-registry.py
python3 -m unittest discover -s plugins/zara-browser/test -t plugins/zara-browser/test
nix flake check
```
