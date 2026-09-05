# zara-coding

`zara-coding` is the Zara-facing coding harness built on `lost-rob0t/prolog-rlm`. The current slices establish safe repository evidence, runtime preflight, a closed SPEC-authoring boundary, and narrowly approval-gated Git mutation before worker spawning or build/test execution is exposed.

## Current surface

- `coding.status` reports whether repository roots are configured and whether the configured Prolog-RLM checkout passes the public `rlm:rlm_ready/0` + `rlm:rlm_version/1` facade.
- `coding.repo.list` discovers Git repositories only at configured roots or their immediate child directories. Results are capped at 100 repositories and discovery scans at most 1,000 child entries; symlink children and deeper recursive traversal are not followed.
- `coding.repo.status` and `coding.repo.inspect` return the same structured repository root, HEAD, branch, dirty state, and changed paths for repositories beneath configured roots.
- `coding.git.diff` returns tracked working-tree changes against `HEAD` as bounded structured numstat evidence, including binary-file distinction, without returning arbitrary patch text.
- `coding.git.log` returns up to 100 commits as structured commit/parent/author/time/subject evidence for an allowed repository.
- `coding.git.branches` returns up to 100 local branches as structured name/commit/upstream evidence for an allowed repository.
- `coding.git.branch.create` creates exactly one new local branch at the repository's current `HEAD`. It requires Zara's canonical tool approval metadata, validates the full `refs/heads/...` name with Git, and uses compare-and-set `update-ref` semantics with an empty expected old OID—the hash-format-independent “ref must not exist” sentinel—so an existing branch is never moved or overwritten.
- `coding.git.worktree.list` parses Git's NUL-delimited porcelain worktree inventory into bounded path/HEAD/branch/detached/locked/prunable evidence. Every reported worktree path must remain inside configured repository roots.
- `coding.spec.catalog` returns Prolog-RLM's canonical closed SPEC structural catalog. The current bridge deliberately supplies an empty assertion registry, so it honestly reports no plugin-owned semantic assertion providers yet.
- `coding.spec.normalize` sends one bounded declarative SPEC source to Prolog-RLM's canonical `rlm_spec_lang:spec_source_normalize/2` path and returns its canonical outcome.

SPEC catalog and normalization use fixed SWI-Prolog goals against `rlm_spec_lang.pl`. SPEC source is passed over stdin; it is never interpolated into the SWI-Prolog goal or command argv. Source is capped at 65,536 characters and execution has a bounded timeout. A Prolog-RLM rejection remains a `rejected` outcome with canonical Prolog evidence rather than being converted into success.

The catalog intentionally does not fabricate semantic providers. Prolog-RLM's trusted assertion registry owns validator/evaluator/observer authority, and its public registry contract has no model-facing registration mutation. Provider-backed validation/freezing therefore remains a later explicit integration slice rather than silently installing Zara-owned callables.

The normalization tool deliberately stops before provider validation, freezing, planning, execution, or verification. It establishes that Zara uses Prolog-RLM's existing SPEC representation rather than creating a second acceptance/task language.

The plugin never shells through a command string. Git and SWI-Prolog probes use argv execution with bounded timeouts. Repository paths are resolved and checked against configured roots before and after Git root discovery. Repository discovery is deliberately shallow and bounded rather than recursively walking arbitrary project trees. Diff summaries, commit history, branch inventory, and worktree inventory are bounded before use. Git operations use fixed revisions, formats, and options rather than caller-controlled Git arguments. `coding.git.diff` fails closed if the changed-file count exceeds its configured request bound; worktree inventory fails closed on over-limit, malformed, contradictory, unsupported, or out-of-boundary records. Branch creation is the only current mutating tool and is approval-gated, fixed to current `HEAD`, and create-only at the ref layer.

## Configuration

```toml
[plugins.zara-coding]
allowed_roots = ["~/Documents/Projects"]
git = "git"
prolog_rlm_checkout = "~/Documents/Projects/prolog-rlm"
swipl = "swipl"
```

If `allowed_roots` or `prolog_rlm_checkout` is absent, the service still loads and reports a degraded status. It does not claim Prolog-RLM readiness or silently widen repository access. Repository tools fail closed when repository roots are unavailable, and SPEC tools fail closed when no Prolog-RLM checkout is configured.

## Architecture direction

This is intentionally not a second agent runtime and not a thin GitHub wrapper. Subsequent slices bind coding intent and verification evidence into Prolog-RLM's canonical `INTENT -> SPEC -> PLAN -> BUILD/EXECUTE -> VERIFY` runtime. GitHub operations stay behind `zara-github`; generic command execution stays behind `zara-shell`; transient desktop/editor context comes from `zara-context` when available.

The next symbolic milestone is trusted provider-backed SPEC validation/freezing and verification evidence. That work must use Prolog-RLM's existing `rlm_assertion`, `rlm_spec`, `rlm_verify`, plan graph, authority, effect, artifact, and agent substrates rather than introducing Zara-owned substitutes.

No arbitrary shell/eval, worktree mutation, branch overwrite/move, build execution, worker spawning, model-installed semantic provider, or model-driven success claim is exposed by the current surface.

## Verification

```sh
python3 -m unittest discover -s plugins/zara-coding/test -t plugins/zara-coding/test
python3 scripts/validate-registry.py
nix flake check
```
