# zara-knowledge

Provider-neutral sourced knowledge retrieval for Zara. The initial remote provider is Brave Search; the public result schema is deliberately not Brave-specific so reference, computational, and local-KB providers can be added without changing Zara's tool shape.

## Evidence contract

Every result contains `provider`, `url`, `title`, bounded `excerpt`, retrieval `timestamp`, and a `local` provenance flag. Results from different providers are not silently collapsed, so conflicting evidence remains attributable. Provider failures are returned separately in `errors` with provider identity and a typed failure kind; one failing provider does not erase successful evidence from another.

## Brave configuration

Configure `zara-knowledge` through Zara's plugin configuration. `default_provider` currently accepts `brave`. The API key may come from `BRAVE_SEARCH_API_KEY`, plugin configuration, or `brave_api_key_file`. Credential files must be mode `0600`. Keys are sent only in the Brave subscription header and are never returned by status/search tools or placed in Nix output.

Supported bounds include `timeout_seconds`, `max_response_bytes`, and `max_results`. Search accepts bounded `count` plus optional `language`, `safe_search` (`off`, `moderate`, `strict`), and Brave freshness text. Returned URLs must be absolute HTTP(S) URLs without embedded credentials.

If Brave is not configured, `knowledge.search` returns an explicit provider `unavailable` error rather than pretending an empty result set is a successful provider response. A configured Brave query that genuinely returns zero results is an empty successful result set.

## Tools

- `knowledge.search` — provider-neutral sourced search results and independent provider errors.
- `knowledge.status` — provider configuration/availability without credential material.

Interactive page operation belongs to `zara-browser`; this plugin only owns knowledge retrieval semantics. Zara core continues to own intent routing and approval policy.

## Verification

```sh
python3 scripts/validate-registry.py
python3 -m unittest discover -s plugins/zara-knowledge/test -t plugins/zara-knowledge/test
nix flake check
```

Tests use fake providers/fake HTTP responses and require no network or real credentials.
