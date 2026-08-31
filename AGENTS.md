# AGENTS.md — zara-plugins

This file guides agentic coding assistants working in this repo.

## Scope
- Applies to the entire repository.
- This repo is the public plugin registry for Zara
  (<https://github.com/lost-rob0t/zara>). It hosts plugin code, the
  machine-readable `plugins.json` catalog, and Nix packaging. Zara runtime
  changes belong in the Zara repository, not here.

## Environment
- Prefer `nix` for all builds, tests, and dev shells.
- Enter the dev shell: `nix develop`.
- Validate the registry: `python3 scripts/validate-registry.py` (or
  `nix flake check`, which runs it plus the plugin test suites).
- Run a plugin's tests: `python3 -m unittest discover -s plugins/<name>/test -t plugins/<name>/test`.

## Repository Layout
- `plugins.json` — the registry. Root level, machine-readable, single source
  of truth for what is published.
- `plugins/<name>/` — one self-contained directory per plugin: entrypoint,
  `README.md`, `test/`, optional `tools/` and assets.
- `scripts/` — registry validation and maintenance scripts.
- `skills/` — repository-local agent skills; read the relevant skill before
  executing that procedure.
- `flake.nix` — exposes every registered plugin as a package plus install
  apps and checks. Registry entries, plugin directories, and flake outputs
  must stay in sync; the validator enforces the first two.

## Registry Invariants
- Every plugin directory must have a `plugins.json` entry, and every entry
  must point at a real directory, entrypoint, and docs file.
- Plugin `name` must match its directory name and Zara `PluginMetadata`
  naming rules (`[a-z0-9][a-z0-9._-]{0,63}`).
- For service plugins, the entrypoint's `create_plugin()` /
  `PluginMetadata(name=...)` must agree with the registry entry's name and
  version. The validator checks this from source.
- Bump `updated` in `plugins.json` whenever the catalog changes.

## Tests
- Every plugin ships deterministic tests under `plugins/<name>/test/`.
- Behavior-changing plugin work is test-driven: failing test first, smallest
  coherent change, green, refactor. Mirror the Zara repository's TDD
  contract.
- Tests must run with the Python standard library (plus pytest when
  available) and must not require network, secrets, or a GUI.
- Integration tests that need a real Zara checkout skip cleanly when Zara is
  absent (see `zara-avatar`'s `RealZaraCompatibilityTest`).

## TDD & Coverage Contract
- Follow the Zara repository's TDD and coverage contract: meaningful
  coverage of changed behavior and failure paths, no backfilled paperwork
  tests, no gaming metrics.
- Plugin changes without tests are incomplete.

## Publishing Workflow
- Publishing is issue-driven. Plugin submissions start as GitHub issues;
  use the `publish-plugin` skill for intake, review, wiring, and closure.
- Never edit `plugins.json` without validating, and never publish a plugin
  whose tests do not pass.

## Nix
- `flake.nix` derives package and check names from `plugins.json`; adding a
  plugin to the registry is enough to expose it.
- Keep the flake pure: no `fetchurl` without pinned hashes, no network
  during checks. Renderer/npm-based assets stay user-installed until a
  reproducible Nix packaging exists for them.

## Git / CI Discipline
- Small, focused diffs. Never mix registry metadata changes with unrelated
  plugin refactors.
- `plugins.json` edits must always travel with the plugin changes they
  describe (version bumps, renames, removals).

## Do Not Do
- Do not add plugins without an issue and a registry entry.
- Do not vendor `node_modules` or build artifacts into plugin directories.
- Do not weaken plugin security postures (loopback binding, bounded queues,
  size limits) to make tests or installs easier.
- Do not add inline comments unless asked; follow each plugin's existing
  style.
- Do not change Zara runtime code from this repository.

## Logging / Style
- Follow each plugin's existing formatting and import grouping
  (stdlib → third-party → local).
- Prefer explicit error messages over silent failures.
- Keep scripts in `scripts/` stdlib-only and executable.
