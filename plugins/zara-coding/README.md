# zara-coding

`zara-coding` is the Zara-facing coding harness built on `lost-rob0t/prolog-rlm`. The current slices establish safe repository evidence, runtime preflight, a closed SPEC-authoring boundary, trusted SPEC validation/freezing, pure repository verification, and narrowly approval-gated Git mutation before worker spawning or build/test execution is exposed.

## Current surface

- `coding.status` reports whether repository roots are configured and whether the configured Prolog-RLM checkout passes the public `rlm:rlm_ready/0` + `rlm:rlm_version/1` facade.
- `coding.repo.list` discovers Git repositories only at configured roots or their immediate child directories. Results are capped at 100 repositories and discovery scans at most 1,000 child entries; symlink children and deeper recursive traversal are not followed.
- `coding.repo.status` and `coding.repo.inspect` return the same structured repository root, HEAD, branch, dirty state, and changed paths for repositories beneath configured roots.
- `coding.git.diff` returns tracked working-tree changes against `HEAD` as bounded structured numstat evidence, including binary-file distinction, without returning arbitrary patch text.
- `coding.git.log` returns up to 100 commits as structured commit/parent/author/time/subject evidence for an allowed repository.
- `coding.git.branches` returns up to 100 local branches as structured name/commit/upstream evidence for an allowed repository.
- `coding.git.branch.create` creates exactly one new local branch at the repository's current `HEAD`. It requires Zara's canonical tool approval metadata, validates the full `refs/heads/...` name with Git, and uses compare-and-set `update-ref` semantics with an empty expected old OID—the hash-format-independent “ref must not exist” sentinel—so an existing branch is never moved or overwritten.
- `coding.git.branch.delete` deletes one local branch only with canonical Zara approval and a caller-supplied full SHA-1 or SHA-256 object ID matching the branch's current head. Before mutation it inspects all bounded linked worktrees and refuses deletion if that branch is checked out anywhere. The final `git update-ref -d` uses the expected object ID as a compare-and-set guard, so a branch that moved after inspection fails closed instead of deleting stale state.
- `coding.git.commit` creates a commit from exactly the repository's existing staged index. It requires canonical Zara approval, a bounded non-empty message, an attached local branch, and a full expected HEAD object ID. It refuses stale HEAD and empty staged deltas before creating the commit object, uses `git write-tree` + `git commit-tree` rather than `git commit` so repository hooks are not executed, passes the message over stdin rather than argv/shell, and advances the branch only through `git update-ref <ref> <new> <expected>` compare-and-set semantics. It never auto-stages files.
- `coding.git.worktree.list` parses Git's NUL-delimited porcelain worktree inventory into bounded path/HEAD/branch/detached/locked/prunable evidence. Every reported worktree path must remain inside configured repository roots.
- `coding.git.worktree.add-detached` creates one detached linked worktree at an exact caller-supplied commit. It requires canonical Zara approval, a non-existing target whose parent already exists inside configured repository roots, a full SHA-1 or SHA-256 object ID that resolves directly to a commit, and fixed-argv `git worktree add --detach`. It never creates or moves a branch.
- `coding.spec.catalog` returns Prolog-RLM's canonical closed SPEC structural catalog plus the exact fixed assertion providers admitted by `coding.spec.compile`.
- `coding.spec.normalize` sends one bounded declarative SPEC source to Prolog-RLM's canonical `rlm_spec_lang:spec_source_normalize/2` path and returns its canonical outcome without provider validation or freezing.
- `coding.spec.compile` sends one bounded declarative SPEC source through Prolog-RLM's canonical `spec_source_compile/4` normalize → validate → freeze path with the immutable `zara-coding` trusted registry. Successful output is a canonical `frozen_spec` with series `zara_coding`, version `1`, and Prolog-RLM's semantic SHA-256 fingerprint.
- `coding.spec.verify-repository` inspects one allowed repository at call time, projects its exact root/HEAD/branch/dirty state into current observed repository evidence, binds observations to the frozen requirement IDs/assertions/verifier identities, and calls Prolog-RLM's pure `rlm_verify:spec_verify/4`. Verification is read-only and does not collect filesystem state from Prolog or grant execution authority.
- `coding.spec.check-repository` provides the direct read-only path for one declarative repository SPEC: it first validates/freezes through the same trusted registry and only if that succeeds inspects current repository state and runs pure verification. Compile rejection is returned without inspecting the repository, and compile and verification outcomes remain separate evidence rather than being collapsed into a synthetic success flag.

The trusted registry is code shipped with the plugin, not model data. It currently admits only `repository_head/1`, `repository_branch/1`, and `repository_clean/1`. All require current repository evidence with trust class `trusted` or `observed`; none has an observer, so SPEC compilation cannot secretly inspect the filesystem or execute Git. Their pure evaluators reconcile separately supplied repository evidence during verification. `repository_branch` accepts the exact branch label already captured by bounded repository inspection, including the explicit `DETACHED` sentinel. Prolog-RLM's assertion registry API deliberately has no public registration mutation, so a model or SPEC cannot install new validators/evaluators/observers.

SPEC catalog, normalization, compilation, and verification use fixed SWI-Prolog goals against Prolog-RLM's canonical modules. SPEC source, frozen SPEC data, and repository evidence are passed over stdin; they are never interpolated into the SWI-Prolog command argv. SPEC source is capped at 65,536 characters, frozen compiler output is bounded, and execution has a bounded timeout. Prolog-RLM rejection remains a structured rejected outcome with canonical Prolog evidence rather than being converted into success.

The plugin never shells through a command string. Git and SWI-Prolog probes use argv execution with bounded timeouts. Repository paths are resolved and checked against configured roots before and after Git root discovery. Repository discovery is deliberately shallow and bounded rather than recursively walking arbitrary project trees. Diff summaries, commit history, branch inventory, and worktree inventory are bounded before use. Git operations use fixed revisions, formats, and options rather than caller-controlled Git arguments. `coding.git.diff` fails closed if the changed-file count exceeds its configured request bound; worktree inventory fails closed on over-limit, malformed, contradictory, unsupported, or out-of-boundary records. Git mutations are approval-gated and stale-safe: branch creation is fixed to current `HEAD` and create-only at the ref layer; deletion requires exact expected-head evidence and rejects checked-out branches; commit consumes only the staged index, runs no repository commit hooks, refuses stale HEAD, and compare-and-set advances only the observed branch value. Detached worktree creation cannot create or move refs, refuses pre-existing or out-of-boundary targets, and verifies that the supplied object ID is the commit object itself before asking Git to materialize it.

## Configuration

```toml
[plugins.zara-coding]
allowed_roots = ["~/Documents/Projects"]
git = "git"
prolog_rlm_checkout = "~/Documents/Projects/prolog-rlm"
swipl = "swipl"
```

If `allowed_roots` or `prolog_rlm_checkout` is absent, the service still loads and reports a degraded status. It does not claim Prolog-RLM readiness or silently widen repository access. Repository tools fail closed when repository roots are unavailable, SPEC tools fail closed when no Prolog-RLM checkout is configured, and repository verification requires both.

## Architecture direction

This is intentionally not a second agent runtime and not a thin GitHub wrapper. The current SPEC path now reaches pure verification for repository HEAD/branch/clean assertions while keeping desired state, observed state, and effect authority separate. `coding.spec.check-repository` is the bounded direct path for requests that need acceptance checking but no planning or mutation. Subsequent slices can bind broader coding intent and additional trusted evidence into Prolog-RLM's canonical `INTENT -> SPEC -> PLAN -> BUILD/EXECUTE -> VERIFY` runtime only where Zara exposes the required composition contracts. GitHub operations stay behind `zara-github`; generic command execution stays behind `zara-shell`; transient desktop/editor context comes from `zara-context` when available.

Planning/execution still waits for canonical Core plugin composition rather than importing another plugin's implementation or creating a parallel runtime. Verification itself does not imply authorization to repair or retry an effect.

No arbitrary shell/eval, branch overwrite/move, auto-staging, build execution, worker spawning, model-installed semantic provider, filesystem-observing Prolog assertion, or model-driven success claim is exposed by the current surface. Worktree mutation is limited to exact detached commits inside configured roots and requires canonical approval.

## Verification

```sh
python3 -m unittest discover -s plugins/zara-coding/test -t plugins/zara-coding/test
python3 scripts/validate-registry.py
nix flake check
```
