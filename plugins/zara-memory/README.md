# zara-memory

`zara-memory` is Zara's scoped adapter boundary for durable symbolic memory. It does not create a second memory database: persistence is delegated to `lost-rob0t/symbolic-memory` or another explicitly injected compatible backend.

## Scope and privacy

The plugin domain represents `session`, `user`, `project`, `machine`, and `global` scopes. The current native symbolic-memory MCP implementation supports only `session`, `project`, and `global`; `user` and `machine` are **not remapped or emulated** and fail as unsupported until the backend implements them.

Transient context is never persisted implicitly. Durable native writes happen only through `memory.remember`, which carries Zara Core's canonical `zara_requires_approval=true` tool metadata. `memory.get` reads one known stable ID and does not mutate state.

Host authority is not model-controlled. Principal, session ID, project remote, source class, and capability grants come from plugin configuration and are passed to symbolic-memory as its host-bound environment. They are never accepted as `memory.remember`/`memory.get` tool arguments. The child process receives only a small environment allowlist plus those explicit symbolic-memory settings, so unrelated ambient secrets are not inherited.

## Native symbolic-memory configuration

```toml
[plugins.zara-memory.symbolic_memory]
executable = "symbolic-memory-mcp"
database = "~/.local/state/zara/symbolic-memory.db"
principal = "zara-local"
session_id = "desktop"
project_remote = "https://github.com/example/project"
source_class = "model_inferred"
capabilities = ["memory_read", "memory_write_session", "memory_write_project"]
```

The database is mutable state and must live outside `/nix/store`. If the executable is absent, `memory.status` reports `symbolic-memory-executable-not-found`; if no backend is configured it reports `symbolic-memory-backend-not-configured`.

The adapter speaks current stateless MCP `2026-07-28` over fixed argv execution with a bounded timeout and no shell interpolation. Native tool failures remain failures; Zara does not manufacture success or symbolic projection evidence.

## Current native surface

- `memory.status` — backend availability plus Zara/native supported scopes.
- `memory.remember` — approval-gated exact-source durable remember with backend-supported scope, retention, and kind.
- `memory.get` — authorized read of one known stable memory ID, preserving backend provenance/lifecycle evidence.

Current symbolic-memory still defers full-corpus search, symbolic-first recall, natural-language forgetting, contradiction/supersession reasoning, and generated-rule activation. `zara-memory` does not recreate those features locally; issue #7 remains open until the backend capabilities exist and are integrated.

The existing `MemoryService` schema boundary remains available for compatible injected backends and continues to enforce explicit scope ownership, schema-constrained predicates, and projection-cleanup evidence for backends that implement recall/forget.

## Verification

```sh
python3 -m unittest discover -s plugins/zara-memory/test -t plugins/zara-memory/test
python3 scripts/validate-registry.py
nix flake check
```

Tests use deterministic fake MCP/backend responses and require no network or live memory service.
