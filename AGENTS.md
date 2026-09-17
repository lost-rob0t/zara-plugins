# AGENTS.md — zara-plugins

This is the repository-wide working model for agents changing Zara's public plugin catalog and plugin implementations. Read it together with the current Zara Core `AGENTS.md`, the plugin's own docs/tests, and the owning GitHub issue/PR.

## Scope and ownership

- This repository is the public plugin registry for `lost-rob0t/zara`.
- It owns independently installable plugin implementations, `plugins.json`, plugin docs/tests/assets, and Nix packaging for the catalog.
- Zara Core/runtime contracts, canonical semantic/runtime behavior, Android/Wear Kotlin/Compose/platform mechanics, and release machinery belong in `lost-rob0t/zara`.
- Before implementing, search current issues and open PRs. Extend an existing plugin/adapter instead of publishing a duplicate.
- Publishing and major provider expansion are issue-driven. Do not invent an untracked public plugin.
- `main` is protected workflow territory: branch + PR, with exact-head CI before completion/merge.

## Mental model: a plugin extends Zara; it does not become Zara

Plugins run behind Zara's existing host/runtime contracts.

- A `ServicePlugin` participates in Zara lifecycle and may expose tools/commands/events through the supported Plugin API.
- Agent-facing tools remain LangChain-compatible (`BaseTool`/`StructuredTool`) when exposed to the conversational agent.
- A plugin must not create a competing runtime, generic tool registry, approval system, scheduler, memory authority, Prolog engine, principal store, or Android authority plane.
- Background work must be bounded and tied to plugin lifecycle (`start`/`stop` or the current managed-worker contract). Do not leave unmanaged immortal threads/processes.
- If a feature needs a missing Core primitive, make/file the smallest Core handoff in `lost-rob0t/zara`, add compatibility coverage, then consume that contract here. Do not copy Core internals into this repo.

## What belongs here

Typical plugin-repo work includes:

- provider backends behind an existing provider-neutral domain;
- home/calendar/comms/service integrations;
- independently installable expert/tool/service plugins;
- provider-specific transport/auth/rate-limit/schema logic;
- plugin-private configuration and migration behavior;
- registry metadata and reproducible packaging.

Native Android behavior does **not** move here merely because someone calls it a plugin. Android `Intent`, `CalendarContract`, Accessibility, permissions, Compose, services, and Wear mechanics stay in Zara's `android/` tree unless a current reviewed issue explicitly specifies a separately packaged capability APK. Such an APK still uses Zara's authority/capability contract rather than inventing one.

## Repository layout

- `plugins.json` — machine-readable publication registry and source of truth for catalog entries.
- `plugins/<name>/` — one self-contained plugin directory: entrypoint, implementation, `README.md`, deterministic `test/`, optional tools/assets.
- `scripts/` — registry/maintenance validation; keep portable scripts stdlib-only where established.
- `skills/` — repository-local agent procedures. Read the relevant skill before using it.
- `flake.nix` — catalog packages/install apps/checks. Registry, directories, metadata, and flake outputs must agree.

## Plugin API and compatibility

- Follow the current Zara Plugin API version used by adjacent plugins; do not silently invent a new API version.
- `PluginMetadata` name/version/API metadata, entrypoint behavior, registry entry, README, and package output must describe the same artifact.
- Service plugins expose `create_plugin()` and lifecycle according to the current Zara host contract.
- Keep import/install behavior compatible with both a source Zara checkout and the installed Zara package when the plugin supports both.
- Cross-repo API changes require explicit consumer tests or compatibility fixtures. Green plugin tests against a stale/mock contract are not enough evidence.
- A plugin may have internal helper classes/actors for bounded ownership, but those are implementation details—not replacement Zara runtimes.

## Registry invariants

- Every published plugin directory has one `plugins.json` entry; every entry points to real code/docs.
- Plugin names follow Zara metadata naming rules (`[a-z0-9][a-z0-9._-]{0,63}`).
- Registry name/version/API type and source `PluginMetadata` must agree.
- Catalog changes update the registry `updated` field as required by the validator.
- Version/registry changes travel in the same PR as the behavior they describe. Do not publish metadata for code that is not present.
- Do not add a second entry for a provider/feature already implemented as part of an existing plugin unless the architecture explicitly calls for a separate package.

## Provider integrations

Provider plugins need stronger boundaries than ordinary pure functions.

### Credentials and principals

- Credentials are host/plugin-owned configuration, never tool/LLM arguments.
- Plugin-private config belongs under Zara's plugin-private XDG path as defined by Core; do not put secrets in `plugins.json`, source, fixtures, logs, Nix derivations, docs examples with live values, or tool output.
- Bind a backend instance to an explicit principal/account. Caller-controlled IDs select resources within that bound principal; they do not choose credentials.
- Test two independently constructed principals/backends for isolation when the provider model is principal-bearing.

### Transport

- Constrain requests to configured/documented origins. Treat caller values as data, not absolute URLs, paths with traversal, headers, or redirect targets.
- Reject credential-bearing cross-origin redirects unless an explicit reviewed protocol requires them and preserves security.
- Bound request/response body size, timeouts, pagination, retries, backoff, queue depth, and fan-out.
- Retry only failures that are safe under the provider protocol. For ambiguous non-idempotent mutation failures, surface an unknown outcome instead of blindly replaying.
- Use provider ETags/versions/idempotency keys/CAS where available.
- Parse provider schemas fail-closed; do not silently coerce malformed security- or identity-relevant fields.

### Mutation verification

- Provider acknowledgement is not proof that requested state exists.
- When the provider exposes a read-back path, the provider-neutral domain should independently observe the result before reporting `verified=true`.
- Preserve the distinction among `accepted`, `verified`, `verification_failed`, stale-version/conflict, and unknown mutation outcome.

## Configuration

- External service plugins own private config under `$XDG_CONFIG_HOME/zarathushtra/plugins/<plugin-name>/` (fallback `~/.config/zarathushtra/plugins/<plugin-name>/`) according to Core's contract.
- Do not move plugin-owned provider settings into Zara root config merely for convenience.
- Environment variables may be bootstrap configuration where the plugin already uses that model; validate them before constructing network requests.
- Never expose secret configuration through status/diagnostic tools. Status should report safe readiness/reason information only.

## Environment

- Prefer Nix for build/test/dev-shell work.
- Enter dev shell: `nix develop`.
- Registry validation: `python3 scripts/validate-registry.py`.
- Full repo/check gate: `nix flake check`.
- Focused plugin unittest discovery: `python3 -m unittest discover -s plugins/<name>/test -t plugins/<name>/test`.
- Follow a plugin's README/CI for additional exact integration gates.

## TDD and coverage

Behavior changes are test-driven.

1. Write/update the deterministic test for the next behavior.
2. Prove it fails for the expected reason.
3. Implement the smallest coherent production change.
4. Run it to green.
5. Refactor while green.
6. Repeat, then run the plugin suite and repository gates.

Tests must be deterministic and should not require live network, real provider accounts, secrets, or GUI interaction. Use fake/scripted provider transports or local test servers that exercise the real parser/auth/retry/verification code.

Cover relevant failure paths, especially:

- malformed/empty/boundary input;
- auth expiry/revocation and secret-safe errors;
- pagination, rate limit, retry/backoff, timeout/cancellation;
- stale version/CAS and provider races;
- ambiguous mutation outcomes and independent postcondition checks;
- principal/account isolation;
- response-size/resource bounds;
- startup/stop/cleanup/restart when lifecycle-managed;
- source versus installed Zara compatibility;
- registry/Nix/install behavior.

Do not backfill cosmetic tests after implementation when ordinary red-green is possible. Do not weaken assertions or bypass security checks to make CI green.

## External dependencies

- Prefer stdlib/existing dependencies when they are adequate.
- Do not make tests depend on ambient undeclared packages.
- Any added dependency must be reproducibly packaged through Nix and represented in install/compatibility tests.
- No live network during Nix checks.
- Do not vendor `node_modules`, virtualenvs, model caches, generated databases, provider credentials, or build artifacts.

## Git and CI discipline

- Keep diffs focused. Do not mix unrelated plugin refactors with registry metadata churn.
- Tests should be committed before/with the implementation in a way that preserves TDD evidence when practical.
- Run focused tests and the full applicable gate before declaring completion.
- After pushing/opening a PR, verify required GitHub Actions for the exact candidate SHA. An older green run is stale.
- Do not merge while required CI is pending/failing.
- Hardware/credentialed provider acceptance may remain an explicit external gate, but ordinary deterministic contract tests still need to pass.

## Style and errors

- Match each plugin's existing formatting/import order (stdlib → third-party → local).
- Prefer explicit, typed/actionable errors over silent fallback.
- Error text/logs must not echo bearer tokens, refresh tokens, passwords, client secrets, auth headers, private payloads, or provider bodies that may contain them.
- Keep helpers focused and boundaries explicit.
- Do not add a repo-wide linter/formatter unless requested.
- Comments should explain non-obvious protocol/invariant reasoning, not narrate obvious code.

## Publishing workflow

- New public plugins start from an owning issue and use the repository `publish-plugin` procedure/skill where applicable.
- Existing plugins may be expanded under an owning issue/worker without creating a duplicate plugin.
- Update README/API examples when behavior/configuration changes.
- Validate `plugins.json`, package/install surfaces, and plugin tests before publication.

## Cross-repo handoffs

When work spans Zara Core and this repo:

1. Identify the owner of the missing contract.
2. Avoid parallel implementations.
3. Land/stack the Core primitive and plugin consumer in explicit PR order.
4. Keep public API changes minimal and versioned/compatible.
5. Link both issues/PRs and run compatibility tests against the exact candidate heads.

For Android provider UX, Core/Android may own account-linking UI/intents while this repo owns the server/provider protocol adapter. Keep credential authority and mutation verification on the side defined by the provider/core contract; do not shuttle raw secrets through Android actions.

## Do not do

- Do not add a public plugin without an issue and registry entry.
- Do not duplicate an existing plugin/provider backend because its PR is still open; stack on or review the owner.
- Do not change Zara Core/runtime code from this repository.
- Do not create a second runtime, scheduler, memory system, policy/approval channel, generic tool registry, or Android authority plane.
- Do not allow caller-controlled provider origins, auth headers, raw Android intents, shell commands, or arbitrary components through provider tools.
- Do not claim `2xx`/accepted means verified when read-back is available.
- Do not weaken loopback/origin/auth/queue/size/timeout/principal boundaries for convenience.
- Do not leak secrets into Git, fixtures, CI logs, diagnostics, Nix, or test failure messages.
- Do not vendor generated dependencies or build artifacts.

Keep the plugin small, bounded, testable, and subordinate to Zara's canonical runtime contracts.