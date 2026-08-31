# Skill: plugin-dev

Develop, test, and validate plugins inside the zara-plugins registry.

## Layout contract

- One self-contained directory per plugin: `plugins/<name>/`.
- Service plugins: entrypoint defines `create_plugin()` returning a
  `zara.plugins.ServicePlugin` whose `PluginMetadata(name=...)` matches the
  directory name and the registry entry.
- Tool plugins: entrypoint defines `register_tools()`/`register_skills()`
  returning LangChain `BaseTool` instances.
- Each plugin ships `README.md`, `test/` (deterministic, stdlib-first,
  network-free), and optional `tools/` and assets.
- The avatar plugin preserves a `<name>/zara-plugin/<name>.py` +
  `<name>/renderer` + `<name>/tools` layout because its installer and
  renderer resolution are layout-relative; do not reshuffle plugin-internal
  layouts without updating the plugin's own tools and tests.

## Workflow

1. Read the plugin's `README.md` and existing tests before changing
   anything.
2. For behavior changes, follow the TDD contract: write the failing test in
   `plugins/<name>/test/`, prove red, make the smallest coherent change,
   prove green, refactor.
3. Keep import grouping (stdlib → third-party → local) and the plugin's
   existing style. No inline comments unless asked.
4. Never weaken security postures: loopback-only binding, bounded queues,
   size limits, worker limits, and timeouts are contractual.
5. If the plugin version changes, update `plugins.json` (`version` and
   `updated`) in the same change.

## Verification gate

```sh
python3 scripts/validate-registry.py
python3 -m unittest discover -s plugins/<name>/test -t plugins/<name>/test
nix flake check
```

All three must pass before the work is considered complete. `nix flake
check` runs the registry validator plus every plugin test suite as checks;
package names are derived from `plugins.json`, so a registry edit is enough
to expose a new plugin.

## Rules

- Do not vendor `node_modules`, build artifacts, or secrets into plugin
  directories.
- Do not edit `plugins.json` without running the validator.
- Do not publish without green tests; registry entries, plugin directories,
  and flake outputs must stay in sync.
- Zara runtime API questions are answered by the Zara repository
  (`zara/plugins/api.py`), not guessed.
