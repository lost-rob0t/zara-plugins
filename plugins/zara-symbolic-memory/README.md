# zara-symbolic-memory

`zara-symbolic-memory` makes persistent Zara memory **symbolic first**. Durable state is an append-only Prolog knowledge base; embeddings are derived Prolog facts that can be deleted and rebuilt without losing memory.

## Invariants

- `memory.pl` is canonical. No vector-only write path exists.
- A memory is a versioned `memory_fact/13`; forgetting appends `memory_tombstone/5` instead of silently mutating history.
- `embeddings.pl` is disposable derived state containing `memory_embedding/6`, `kb_clause/4`, and `kb_embedding/5` facts.
- `prolog/query_rules.pl` controls scope visibility, exact/symbolic admission, embedding threshold, recency, confidence, importance, and final hybrid ranking.
- Querying fails closed when SWI-Prolog is required but unavailable.
- Reindexing reconstructs embeddings from the canonical memory facts plus configured `.pl` KB roots.

## Tools

| Tool | Purpose |
| --- | --- |
| `memory.remember` | Assert/update a typed symbolic memory and derive its embedding |
| `memory.query` | Run Prolog-governed hybrid retrieval across memory and Prolog KB clauses |
| `memory.forget` | Append a tombstone for a memory id |
| `memory.reindex` | Rebuild the entire derived embedding file |
| `memory.status` | Inspect canonical/derived paths and runtime readiness |

## Configuration

```toml
[plugins.zara-symbolic-memory]
enabled = true
require_prolog = true
data_dir = "~/.local/share/zara/symbolic-memory"
kb_roots = ["~/.config/zara/kb", "~/Documents/Projects/prolog-rlm/experts"]
embedding_backend = "ollama" # disabled | ollama | openai-compatible
embedding_model = "nomic-embed-text"
ollama_url = "http://127.0.0.1:11434"
```

For an OpenAI-compatible embedding service, set `embedding_backend = "openai-compatible"`, `embedding_endpoint` to the API root (for example `https://host/v1`), and optionally `embedding_api_key`.

The plugin deliberately does not copy secrets into Prolog facts. Only embedding model identifiers, dimensions, hashes, and vectors are stored.

## Core integration

This plugin is designed to be selected as Zara's memory provider. Until core exposes the memory-provider bridge, the plugin still offers its explicit `memory.*` surface, but it must not be described as replacing the built-in `MemoryManager`.
