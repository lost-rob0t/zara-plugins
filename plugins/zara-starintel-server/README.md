# zara-starintel-server

`zara-starintel-server` gives Zara access to the complete HTTP surface exposed by a StarIntel Server. It uses the server's live discovery documents instead of freezing one client version into the plugin:

- `GET /api/v1/capabilities`
- `GET /client-manifest.json`
- `GET /openapi.json`
- every operation advertised by the client manifest
- any same-origin legacy or newly deployed route through the bounded generic request tool

The plugin does not bypass StarIntel authorization. Zara can do everything permitted by the configured API key's scopes, including document and target operations, user and credential administration, and destructive operations.

## Zara tools

- `starintel_status` — show secret-safe local configuration state and optionally call `GET /health`.
- `starintel_capabilities` — fetch the live capabilities document.
- `starintel_api_operations` — list live operation IDs, methods, paths, authorities, scopes, request schemas, and responses.
- `starintel_call_operation` — call any operation by its live `operation_id`, with JSON path parameters, query parameters, body, and headers.
- `starintel_api_request` — issue a bounded `GET`, `POST`, `PUT`, `PATCH`, or `DELETE` against any relative StarIntel path. It supports JSON, form, and text bodies.

Use `starintel_call_operation` when the route appears in the client manifest. Use `starintel_api_request` for legacy views, OAuth routes, or a server route deployed after this plugin version.

All tool results contain the HTTP status, success flag, selected safe response headers, parsed JSON data when present, and the StarIntel correlation ID when returned. Non-2xx API responses are returned as structured results so Zara can inspect and act on them.

## Configuration

```toml
[plugins.zara-starintel-server]
enabled = true
base_url = "https://starintel.actor"
allow_insecure_http = false
timeout_seconds = 30
max_request_bytes = 2097152
max_response_bytes = 8388608
```

`ZARA_STARINTEL_URL` overrides `base_url`.

Remote HTTP is rejected by default. HTTPS is required for remote servers. Loopback HTTP is allowed for local development; set `allow_insecure_http = true` only for an intentionally unsecured remote development server.

## Authentication

The plugin sends an API key as `Authorization: Bearer ...`. Put the key in the plugin's private XDG directory:

```sh
install -d -m 700 ~/.config/zarathushtra/plugins/zara-starintel-server
install -m 600 /dev/null ~/.config/zarathushtra/plugins/zara-starintel-server/api-key
read -rsp 'StarIntel API key: ' STARINTEL_KEY
printf '\n'
printf '%s\n' "$STARINTEL_KEY" > ~/.config/zarathushtra/plugins/zara-starintel-server/api-key
unset STARINTEL_KEY
```

For first-server bootstrap, place the bootstrap secret in the same directory as `bootstrap-secret` with mode `0600`. It is sent only to `POST /auth/bootstrap`.

Environment overrides are also supported:

```sh
export ZARA_STARINTEL_API_KEY_FILE=/run/secrets/starintel-api-key
export ZARA_STARINTEL_BOOTSTRAP_SECRET_FILE=/run/secrets/starintel-bootstrap
```

Direct environment values are supported as `ZARA_STARINTEL_API_KEY` and `ZARA_STARINTEL_BOOTSTRAP_SECRET`. File-backed secrets are preferred for long-running services. Secret values are never returned by status or included in configuration representations. Secret files must be regular, non-symlink files without group or world permissions.

## Calling operations

First list operations:

```text
starintel_api_operations(refresh=true)
```

Then call an advertised operation:

```text
starintel_call_operation(
  operation_id="auth.users.password.reset",
  path_parameters_json="{\"username\":\"operator\"}",
  body_json="{\"password\":\"replacement\",\"must_change_password\":true}"
)
```

The client URL-escapes path parameters and rejects missing, extra, or unresolved parameters.

## Generic requests

Query parameters, bodies, and custom headers use JSON strings:

```text
starintel_api_request(
  method="POST",
  path="/new/document/person",
  query_json="{\"tenant\":\"default\"}",
  body_json="{\"dtype\":\"person\",\"name\":\"Ada\"}",
  body_format="json",
  headers_json="{\"Idempotency-Key\":\"request-1\"}"
)
```

`body_format` is `json`, `form`, or `text`. Form bodies require a JSON object; text bodies require a JSON string. Authorization, bootstrap, cookie, proxy authorization, and host headers cannot be overridden by tool arguments. Absolute URLs, cross-origin paths, embedded queries/fragments, control characters, and unsupported HTTP methods are rejected.

## Nix

```sh
nix build github:lost-rob0t/zara-plugins#zara-starintel-server
```

When selected through the declarative Zara Home Manager plugin registry, the discovery entry and runtime library are linked automatically.

## License

GPL-3.0-or-later.
