# zara-plugins

Public, discoverable plugins for [Zara](https://github.com/lost-rob0t/zara).
Open an issue to publish your plugin.

Downstream Zara clients discover plugins through the machine-readable registry
at [`plugins.json`](plugins.json) and install them either with each plugin's
bundled tool, with Nix, or (once landed in Zara) with a native
`zara plugin install` command.

## Catalog

| Plugin | Version | Type | Description |
| --- | --- | --- | --- |
| [zara-agent-zero](plugins/zara-agent-zero/) | 0.1.0 | service | Delegate selected Zara work to Agent Zero through the A0 connector |
| [zara-avatar](plugins/zara-avatar/) | 0.1.0 | service | Zara-owned 3D avatar presentation (VRM renderer, expression, lip sync) |
| [zara-discord](plugins/zara-discord/) | 0.2.0 | service | Talk to Zara through Discord with access controls, bare mentions, and spontaneous replies |
| [zara-persona](plugins/zara-persona/) | 0.1.0 | service | Operator-owned persona context with optional SWI-Prolog |

## Registry

`plugins.json` is the single source of truth for what this repository ships.
It lists every published plugin with the metadata downstream clients need to
render a catalog, resolve a download, and verify compatibility:

| Field | Meaning |
| --- | --- |
| `schema_version` | Registry schema version consumers implement |
| `plugins[].name` | Plugin name; matches Zara `PluginMetadata` naming rules |
| `plugins[].version` | Published version, verified against the entrypoint source |
| `plugins[].api_version` | Zara plugin API version the plugin targets (`"1"` today) |
| `plugins[].plugin_type` | `service` (ServicePlugin) or `tool` (LangChain tool plugins) |
| `plugins[].path` | Directory in this repository holding the plugin |
| `plugins[].entrypoint` | Python entrypoint inside `path` (`create_plugin()` for services) |
| `plugins[].docs` | Plugin README, relative to `path` |
| `plugins[].install` | Ready-to-run install commands (tool and Nix) |
| `plugins[].nix` | Nix flake/package references for Nix-based installs |

Clients fetch the registry from the raw URL (`registry_raw`), render the
catalog, and install by checking out this repository (or a Nix flake
reference) and copying the plugin entrypoint into Zara's plugin search path
(`~/.zarathushtra/plugins` by default; configurable through
`[modules].search_paths` in Zara's `config.toml`).

The registry is validated on every change by
[`scripts/validate-registry.py`](scripts/validate-registry.py) (also wired as
a flake check), so entries can never drift from the plugin tree.

## Install

Every plugin directory is self-contained. Example for `zara-avatar`:

```sh
# Bundled installer (copies plugin into ~/.zarathushtra/plugins, sets up renderer)
python3 plugins/zara-avatar/tools/zara-avatar install

# Or via Nix
nix run github:lost-rob0t/zara-plugins#zara-avatar -- install
```

Per-plugin details live in each plugin's `README.md`. For example, install the
Discord service plugin with:

```sh
nix run github:lost-rob0t/zara-plugins#zara-discord -- install
```

Package-only bridge/context plugins keep runtime connection state outside the
Nix store:

```sh
nix build github:lost-rob0t/zara-plugins#zara-agent-zero
nix build github:lost-rob0t/zara-plugins#zara-persona
```

### Flake

This repository is a Nix flake. Every registered plugin is exposed
automatically as a package, with install apps and checks:

```sh
nix flake show github:lost-rob0t/zara-plugins
nix build github:lost-rob0t/zara-plugins#zara-agent-zero # Agent Zero bridge
nix build github:lost-rob0t/zara-plugins#zara-avatar     # plugin package
nix build github:lost-rob0t/zara-plugins#zara-discord    # Discord plugin package
nix build github:lost-rob0t/zara-plugins#zara-persona    # persona context plugin
nix build github:lost-rob0t/zara-plugins#zara-plugins    # aggregate of all plugins
nix run github:lost-rob0t/zara-plugins#zara-avatar -- install
nix flake check github:lost-rob0t/zara-plugins           # registry + plugin test suites
```

Packages install to `share/zara/plugins/<name>/` and expose the plugin's
CLI (when it ships one) on `bin/<name>`.

## Publish a plugin

1. Open an issue describing the plugin: name, what it does, entrypoint
   layout, and (for service plugins) its Zara plugin API version.
2. A maintainer (or agent) reviews it against the
   [publish-plugin skill](skills/publish-plugin/SKILL.md): self-contained
   layout, tests, no secrets, license compatibility, registry entry.
3. The plugin lands under `plugins/<name>/` with an entry in `plugins.json`,
   and `scripts/validate-registry.py` plus the flake checks must pass.

Plugin requirements:

- one directory per plugin: `plugins/<name>/` with the Python entrypoint,
  a `README.md`, and tests;
- service plugins expose `create_plugin()` returning a
  `zara.plugins.ServicePlugin` with matching `PluginMetadata`;
- tool plugins expose `register_tools()`/`register_skills()` returning
  LangChain `BaseTool` instances;
- stdlib-only Python where possible; any dependency must be stated in the
  issue and installable through the flake;
- GPL-3.0-or-later compatible licensing.

## For agents

Agents working in this repository read [`AGENTS.md`](AGENTS.md) first; repo
skills live under [`skills/`](skills/):

- [`skills/plugin-dev/`](skills/plugin-dev/SKILL.md) — develop, test, and
  validate plugins in this repository
- [`skills/publish-plugin/`](skills/publish-plugin/SKILL.md) — take a
  publishing issue from intake to a merged registry entry

## License

GPL-3.0-or-later. Each plugin states its own license in the registry and its
README.
