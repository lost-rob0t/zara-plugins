# zara-knowledge

Federated sourced knowledge retrieval for Zara. Version 0.2 adds first-class **wiki gates** beside the existing Brave Search provider, plus provenance-preserving local wiki imports.

## Search model

`knowledge.search` can combine:

- Brave web search;
- locally imported wiki pages;
- explicitly selected live wiki gates.

Results stay provider-neutral and retain `provider`, `gate`, URL, title, bounded excerpt, retrieval/revision timestamp, and local/remote provenance. Conflicting evidence is not silently collapsed. Provider and gate failures are returned independently.

Live wiki fan-out is explicit and bounded. Zara never blasts a query at every known wiki just because the catalog knows about them.

## Wiki gates

A gate is a named wiki source plus its engine and endpoint metadata.

Built-in Wikimedia language families are generated from the gate name rather than hardcoded per language:

- `wikipedia:<language>`
- `wiktionary:<language>`
- `wikibooks:<language>`
- `wikinews:<language>`
- `wikiquote:<language>`
- `wikisource:<language>`
- `wikiversity:<language>`
- `wikivoyage:<language>`

Named global gates include `wikidata`, `commons`, `meta`, `mediawiki`, `species`, and `wikifunctions`. Technical presets include ArchWiki, the official NixOS Wiki, Gentoo Wiki, Debian Wiki, Ubuntu Wiki, EmacsWiki, and Rosetta Code.

The gate catalog also exposes engine families for operator-defined sources: MediaWiki, Wikidata, DokuWiki, MoinMoin, XWiki, TWiki, Foswiki, PmWiki, TiddlyWiki, Wiki.js, BookStack, Gollum, Ikiwiki, Gitit, Oddmuse, TikiWiki, and Confluence-style wikis.

Direct native search/import is implemented for MediaWiki-compatible gates. Other engine gates remain explicit and can use Brave site-search fallback when Brave is configured. They never pretend to support native import.

Example plugin configuration:

```toml
[plugins.zara-knowledge]
wiki_max_gates = 6
wiki_default_gates = ["wikipedia:en", "wikidata"]
wiki_store_path = "~/.local/share/zarathushtra/zara-knowledge/wiki.sqlite3"

[plugins.zara-knowledge.wiki_gates.internal]
base_url = "http://127.0.0.1:8080"
api_url = "http://127.0.0.1:8080/w/api.php"
engine = "mediawiki"
```

Remote custom gates require HTTPS. Loopback HTTP is allowed for local/self-hosted development. Gate and result URLs containing embedded credentials are rejected.

## Import and local search

`wiki.import` fetches one MediaWiki page and stores:

- gate identity;
- page ID;
- title and canonical source URL;
- revision ID and revision timestamp;
- source content;
- categories and links;
- Wikidata item ID when exposed by page properties;
- local import timestamp.

Imports are upserted by `(gate, page_id)` in SQLite. `wiki.local_search` searches this store without network access.

## Tools

- `knowledge.search` — federated Brave + imported wiki + selected live wiki search.
- `knowledge.status` — provider status, gate catalog, and local import count.
- `wiki.gates` — named gates, Wikimedia family templates, and supported engine families.
- `wiki.search` — bounded live search of explicitly selected gates.
- `wiki.import` — import one page from a native wiki gate.
- `wiki.local_search` — search imported pages locally.

## Brave configuration

Configure the Brave key with `BRAVE_SEARCH_API_KEY`, plugin configuration, or `brave_api_key_file`. Credential files must be mode `0600`. Keys are never returned by tools or written into Nix output.

Bounds include `timeout_seconds`, `max_response_bytes`, `max_results`, and `wiki_max_gates`.

## Verification

```sh
python3 scripts/validate-registry.py
python3 -m unittest discover -s plugins/zara-knowledge/test -t plugins/zara-knowledge/test
nix flake check
```

Tests use fake providers/responses and require no live network, account, secret, or GUI.
