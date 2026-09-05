# zara-coding

`zara-coding` is the Zara-facing coding harness built on `lost-rob0t/prolog-rlm`. The current slices establish safe repository evidence, runtime preflight, and a closed SPEC-authoring boundary before any Git mutation, worker spawning, or build/test execution is exposed.

## Current surface

- `coding.status` reports whether repository roots are configured and whether the configured Prolog-RLM checkout passes the public `rlm:rlm_ready/0` + `rlm:rlm_version/1` facade.
- `coding.repo.inspect` returns structured repository root, HEAD, branch, dirty state, and changed paths for repositories beneath configured roots.
- `coding.git.log` returns up to 100 commits as structured commit/parent/author/time/subject evidence for an allowed repository.
- `coding.spec.normalize` sends one bounded declarative SPEC source to Prolog-RLM's canonical `rlm_spec_lang:spec_source_normalize/2` path and returns its canonical outcome.

SPEC source is passed over stdin; it is never interpolated into the SWI-Prolog goal or command argv. The Prolog goal is fixed, source is capped at 65,536 characters, and execution has a bounded timeout. A Prolog-RLM rejection remains a `rejected` outcome with the canonical Prolog evidence rather than being converted into success.

The normalization tool deliberately stops before provider validation, freezing, planning, execution, or verification. It establishes that Zara uses Prolog-RLM's existing SPEC representation rather than creating a second acceptance/task language.

The plugin never shells through a command string. Git and SWI-Prolog probes use argv execution with bounded timeouts. Repository paths are resolved and checked against configured roots before and after Git root discovery. Commit history is capped before Git executes, and the tool exposes only the fixed structured `git log` format rather than caller-controlled format/option strings.

## Configuration

```toml
[plugins.zara-coding]
allowed_roots = ["~/Documents/Projects"]
git = "git"
prolog_rlm_checkout = "~/Documents/Projects/prolog-rlm"
swipl = "swipl"
```

If `allowed_roots` or `prolog_rlm_checkout` is absent, the service still loads and reports a degraded status. It does not claim Prolog-RLM readiness or silently widen repository access. Repository tools fail closed when repository roots are unavailable, and `coding.spec.normalize` fails closed when no Prolog-RLM checkout is configured.

## Architecture direction

This is intentionally not a second agent runtime and not a thin GitHub wrapper. Subsequent slices bind coding intent and verification evidence into Prolog-RLM's canonical `INTENT -> SPEC -> PLAN -> BUILD/EXECUTE -> VERIFY` runtime. GitHub operations stay behind `zara-github`; generic command execution stays behind `zara-shell`; transient desktop/editor context comes from `zara-context` when available.

The next symbolic milestone is provider-backed SPEC validation/freezing and verification evidence. That work must use Prolog-RLM's existing `rlm_spec`, `rlm_verify`, plan graph, authority, effect, artifact, and agent substrates rather than introducing Zara-owned substitutes.

No arbitrary shell/eval, Git mutation, build execution, worker spawning, or model-driven success claim is exposed by the current read-only surface.

## Verification

```sh
python3 -m unittest discover -s plugins/zara-coding/test -t plugins/zara-coding/test
python3 scripts/validate-registry.py
nix flake check
```
