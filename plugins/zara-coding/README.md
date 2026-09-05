# zara-coding

`zara-coding` is the Zara-facing coding harness built toward `lost-rob0t/prolog-rlm`. This first published slice establishes the safe repository and runtime preflight boundary before mutating Git, spawning workers, or exposing build/test execution.

## Current surface

- `coding.status` reports whether repository roots are configured and whether the configured Prolog-RLM checkout passes the public `rlm:rlm_ready/0` + `rlm:rlm_version/1` facade.
- `coding.repo.inspect` returns structured repository root, HEAD, branch, dirty state, and changed paths for repositories beneath configured roots.

The plugin never shells through a command string. Git and SWI-Prolog probes use argv execution with bounded timeouts. Repository paths are resolved and checked against configured roots before and after Git root discovery.

## Configuration

```toml
[plugins.zara-coding]
allowed_roots = ["~/Documents/Projects"]
prolog_rlm_checkout = "~/Documents/Projects/prolog-rlm"
swipl = "swipl"
```

If `allowed_roots` or `prolog_rlm_checkout` is absent, the service still loads and reports a degraded status. It does not claim Prolog-RLM readiness or silently widen repository access.

## Architecture direction

This is intentionally not a second agent runtime and not a thin GitHub wrapper. Subsequent slices bind coding intent and verification evidence into Prolog-RLM's canonical `INTENT -> SPEC -> PLAN -> BUILD/EXECUTE -> VERIFY` runtime. GitHub operations stay behind `zara-github`; generic command execution stays behind `zara-shell`; transient desktop/editor context comes from `zara-context` when available.

No arbitrary shell/eval, Git mutation, build execution, worker spawning, or model-driven success claim is exposed by this initial read-only slice.

## Verification

```sh
python3 -m unittest discover -s plugins/zara-coding/test -t plugins/zara-coding/test
python3 scripts/validate-registry.py
nix flake check
```
