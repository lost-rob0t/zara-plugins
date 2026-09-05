# zara-agent-zero

`zara-agent-zero` lets Zara delegate selected work to an existing Agent Zero instance through Agent Zero's native external HTTP API.

It does not start Agent Zero, duplicate Agent Zero's runtime, or create a second bridge protocol. Message delegation uses the runtime route registered by `helpers.api.register_api_route`:

- `POST /api/api_message`
- `X-API-KEY: <Agent Zero API token>`

The native response contains Agent Zero's `context_id` and `response` fields.

## Zara tools

- `agent_zero_status` — report whether the native API URL and API key are configured. It does not expose the key or invent a capabilities endpoint.
- `agent_zero_message` — send one message/task through `/api/api_message`. The result includes Agent Zero's `context_id`; pass it back on later calls to continue the same Agent Zero conversation. Optional `project_name`, `agent_profile`, and `lifetime_hours` map directly to Agent Zero's native request fields.

## Configuration

```toml
[plugins.zara-agent-zero]
enabled = true
base_url = "http://127.0.0.1:5000"
api_key = ""
allow_remote = false
timeout_seconds = 60
max_message_chars = 20000
max_response_bytes = 1048576
```

The port above is only an example. Configure the actual Agent Zero URL; the plugin does not assume a WebUI port.

Runtime environment overrides keep connection secrets outside Git and the Nix store:

```sh
export ZARA_AGENT_ZERO_URL='http://127.0.0.1:5000'
export ZARA_AGENT_ZERO_API_KEY='...'
```

`ZARA_AGENT_ZERO_API_KEY` is sent only as Agent Zero's native `X-API-KEY` request header. The old session-cookie connector path is not used.

## Agent Zero token

Agent Zero exposes the API token under **Settings > External Services**. The current Agent Zero source protects `api/api_message.py` with the API-key middleware; the generic API router maps that built-in handler to `/api/api_message`.

## Network policy

By default `base_url` must resolve syntactically to `localhost` or a loopback IP. Set `allow_remote = true` only when Zara is intentionally connecting to a remote Agent Zero instance. Requests are bounded by timeout, message length, and response byte limits.

## Nix

```sh
nix build github:lost-rob0t/zara-plugins#zara-agent-zero
```

When selected through the declarative Zara Home Manager plugin registry, its discovery entry and runtime library are linked automatically.

## License

GPL-3.0-or-later.
