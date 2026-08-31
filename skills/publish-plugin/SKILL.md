# Skill: publish-plugin

Take a plugin publishing issue in this repository from intake to a merged,
validated registry entry. Publishing is issue-driven: no plugin lands
without an issue and a registry entry.

## Intake

1. Read the issue. Confirm it states: plugin name, purpose, entrypoint
   layout, Zara plugin API version (services), dependencies, and license.
2. Confirm the plugin name follows Zara `PluginMetadata` naming rules:
   `[a-z0-9][a-z0-9._-]{0,63}`.
3. If information is missing, ask on the issue before wiring anything.

## Review

Check the submission against these requirements before any code lands:

- self-contained directory layout (`plugins/<name>/` with entrypoint,
  `README.md`, `test/`);
- service plugins expose `create_plugin()` / `ServicePlugin`; tool plugins
  expose `register_tools()`/`register_skills()` returning LangChain
  `BaseTool` instances;
- deterministic tests included and green; stdlib-only Python where
  possible; any dependency stated in the issue and installable through the
  flake;
- GPL-3.0-or-later compatible license;
- no vendored `node_modules`, build artifacts, or secrets;
- security posture intact for service plugins: loopback-only binding,
  bounded queues/connections/workers, size limits, timeouts.

Reject with actionable issue comments rather than partially wiring a
non-compliant plugin.

## Wire

1. Add the plugin under `plugins/<name>/` following the `plugin-dev` skill
   layout contract.
2. Add a `plugins.json` entry with all required fields (`name`, `version`,
   `api_version`, `plugin_type`, `description`, `path`, `entrypoint`,
   `docs`, `license`, plus `tags`, `install`, `nix` where applicable) and
   bump `updated`.
3. Nothing else needs wiring for the flake: packages and checks derive from
   `plugins.json`.

## Verify

```sh
python3 scripts/validate-registry.py
python3 -m unittest discover -s plugins/<name>/test -t plugins/<name>/test
nix flake check
```

The validator enforces name/directory/entrypoint agreement and that the
service entrypoint's `PluginMetadata` name and version match the registry
entry.

## Close

- Land the plugin and registry entry in one focused change (registry
  metadata never travels with unrelated refactors).
- Announce on the issue with the catalog line and install commands; close
  the issue only after the gate passes on the merged state.
