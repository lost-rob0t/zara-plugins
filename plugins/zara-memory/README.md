# zara-memory

`zara-memory` is Zara's scoped adapter boundary for durable symbolic memory. It does not create a second memory database: persistence is delegated to a configured backend compatible with `lost-rob0t/symbolic-memory`.

## Scope and privacy

The domain supports explicit `session`, `user`, `project`, `machine`, and `global` scopes. Every operation includes a scope owner, and backend responses are rejected if they cross that requested scope/owner boundary. Plugin-defined schemas restrict which scopes and fact predicates a consumer may write.

Natural-language text is retained losslessly alongside structured facts and provenance. Facts reject rule/control syntax and unregistered predicates. Transient context is never persisted implicitly; callers must use an explicit memory write path.

Forgetting is delegated to the backend and requires projection-cleanup evidence so stale symbolic projections are not silently orphaned.

## Backend availability

The registry plugin intentionally starts without a persistence backend. `memory.status` reports `symbolic-memory-backend-not-configured` rather than pretending durable memory is available. A runtime adapter can inject a compatible backend; unsupported backend capabilities such as recall/search/forget fail explicitly instead of being reimplemented locally.

Mutable memory data belongs to the configured backend's writable state directory. Nothing in this plugin writes mutable private state into the Nix store.

## Verification

```sh
python3 -m unittest discover -s plugins/zara-memory/test -t plugins/zara-memory/test
python3 scripts/validate-registry.py
nix flake check
```

Tests use in-memory fake backends only and require no network or external memory service.
