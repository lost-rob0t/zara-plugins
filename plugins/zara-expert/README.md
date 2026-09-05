# zara-expert

`zara-expert` is the reusable bounded Prolog expert-system host for Zara plugins.

It keeps knowledge bases and mutable facts isolated by plugin namespace, separates session facts from persistent facts, rejects unsafe executable Prolog terms before backend execution, forwards hard query/result limits, and returns structured query/explanation evidence.

## Runtime model

The plugin is a Zara API v1 service plugin. Mutable state lives under `$XDG_DATA_HOME/zarathushtra/zara-expert` by default, never in the immutable Nix package. A backend can be injected by a host integration; when no SWI-Prolog backend is configured the service reports `unavailable` and query/explain operations fail explicitly instead of pretending reasoning succeeded.

Other plugins register their own namespace and KB paths through `ExpertHost.register()`. Cross-plugin state mutation is not implicit.

## Safe operations

- bounded `query` and `explain` calls;
- ground-fact `assert_fact` and idempotent `retract_fact`;
- separate session and persistent state files;
- namespace validation and atomic state writes;
- explicit backend failure propagation.

Arbitrary directives, shell/process predicates, consult/module loading from untrusted terms, assertion/retraction predicates inside query text, and compound control syntax are rejected before the backend sees them.

## Verification predicates

Domain plugins can define predicates such as `can_handle/1`, `required_tools/2`, `plan/2`, and `verify/2` inside their own KB. The host returns backend evidence; a model claim is never treated as proof.

## Tests

```sh
python3 -m unittest discover -s plugins/zara-expert/test -t plugins/zara-expert/test
python3 scripts/validate-registry.py
nix flake check
```
