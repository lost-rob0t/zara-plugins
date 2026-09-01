# zara-agent-zero

`zara-agent-zero` lets Zara delegate selected work to an existing Agent Zero instance through Agent Zero's bundled `_a0_connector` HTTP API.

It does not start Agent Zero, duplicate Agent Zero's runtime, or create a second bridge protocol. The plugin uses:

- `POST /api/plugins/_a0_connector/v1/capabilities`
- `POST /api/plugins/_a0_connector/v1/message_send`

## Zara tools

- `agent_zero_status` — inspect the connector protocol, version, auth state, and advertised capabilities.
- `agent_zero_message` — send one message/task. The result includes Agent Zero's `context_id`; pass it back on later calls to continue the same Agent Zero conversation. Optional `project_name` and `agent_profile` route through Agent Zero's existing connector semantics.

## Configuration

```toml
[plugins.zara-agent-zero]
enabled = true
base_url = "http://127.0.0.1:5000"
allow_remote = false
timeout_seconds = 60
max_message_chars = 20000
max_response_bytes = 1048576
```

The port above is only an example. Configure the actual Agent Zero URL; the plugin does not assume a WebUI port.

Runtime environment overrides keep connection secrets outside Git and the Nix store:

```sh
export ZARA_AGENT_ZERO_URL='http://127.0.0.1:5000'
export ZARA_AGENT_ZERO_COOKIE='session=...'
```

`ZARA_AGENT_ZERO_COOKIE` is sent as the HTTP `Cookie` header for Agent Zero instances with login enabled. If Agent Zero reports that auth is not required, no cookie is needed.

## Network policy

By default `base_url` must resolve syntactically to `localhost` or a loopback IP. Set `allow_remote = true` only when Zara is intentionally connecting to a remote Agent Zero instance. Requests are bounded by timeout, message length, and response byte limits.

## Nix

```sh
nix build github:lost-rob0t/zara-plugins#zara-agent-zero
```

When selected through the declarative Zara Home Manager plugin registry, its discovery entry and runtime library are linked automatically.

## License

GPL-3.0-or-later.
