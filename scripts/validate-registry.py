#!/usr/bin/env python3
"""Validate plugins.json against the plugins/ tree.

Registry invariants enforced here keep downstream Zara clients, the flake,
and human contributors in agreement:

- plugins.json parses and uses a supported schema_version;
- every entry carries the required metadata with valid shapes;
- plugin names follow Zara's PluginMetadata naming rules;
- entrypoints and docs exist inside their plugin directory;
- service entrypoints define create_plugin() and register the same
  name and version that the registry publishes;
- no unregistered plugin directories exist and no duplicate names exist.

Exit code 0 means the registry is consistent; nonzero means broken.
"""

from __future__ import annotations

import ast
import json
import re
import shlex
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "plugins.json"
PLUGINS_DIR = ROOT / "plugins"

SUPPORTED_SCHEMA_VERSIONS = {1}
ALLOWED_PLUGIN_TYPES = {"service", "tool"}
GENERATED_FLAKE_LICENSE = "GPL-3.0-or-later"
GENERATED_FLAKE_SOURCE = "github:lost-rob0t/zara-plugins"
CANONICAL_REGISTRY_URL = "https://github.com/lost-rob0t/zara-plugins"
CANONICAL_REGISTRY_RAW_URL = (
    "https://raw.githubusercontent.com/lost-rob0t/zara-plugins/main/plugins.json"
)
REQUIRED_FIELDS = (
    "name",
    "version",
    "api_version",
    "plugin_type",
    "description",
    "path",
    "entrypoint",
    "docs",
    "license",
)
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class RegistryError(Exception):
    pass


def _errors_from(callable_):
    try:
        callable_()
    except RegistryError as error:
        return [str(error)]
    return []


def load_registry() -> dict:
    try:
        document = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RegistryError("plugins.json is missing at the repository root")
    except json.JSONDecodeError as error:
        raise RegistryError(f"plugins.json is not valid JSON: {error}")
    if not isinstance(document, dict):
        raise RegistryError("plugins.json must contain a JSON object")
    schema_version = document.get("schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise RegistryError(
            f"unsupported schema_version {schema_version!r}; "
            f"supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )
    updated = document.get("updated")
    if not isinstance(updated, str) or updated != updated.strip():
        raise RegistryError("plugins.json updated must be an exact YYYY-MM-DD calendar date")
    try:
        parsed_updated = date.fromisoformat(updated)
    except ValueError as error:
        raise RegistryError(
            "plugins.json updated must be an exact YYYY-MM-DD calendar date"
        ) from error
    if parsed_updated.isoformat() != updated:
        raise RegistryError("plugins.json updated must be an exact YYYY-MM-DD calendar date")
    if document.get("registry") != CANONICAL_REGISTRY_URL:
        raise RegistryError(
            f"plugins.json registry URL must be {CANONICAL_REGISTRY_URL!r}"
        )
    if document.get("registry_raw") != CANONICAL_REGISTRY_RAW_URL:
        raise RegistryError(
            f"plugins.json registry_raw URL must be {CANONICAL_REGISTRY_RAW_URL!r}"
        )
    search_paths = document.get("plugin_search_paths")
    if (
        not isinstance(search_paths, list)
        or not search_paths
        or any(
            not isinstance(path, str)
            or not path.strip()
            or path != path.strip()
            for path in search_paths
        )
        or len(search_paths) != len(set(search_paths))
    ):
        raise RegistryError(
            "plugins.json plugin_search_paths must be a non-empty list of unique canonical strings"
        )
    if not isinstance(document.get("plugins"), list):
        raise RegistryError("plugins.json must contain a 'plugins' array")
    return document


def validate_entry(entry: dict) -> None:
    if not isinstance(entry, dict):
        raise RegistryError("every registry entry must be a JSON object")
    for field in REQUIRED_FIELDS:
        value = entry.get(field)
        if not isinstance(value, str) or not value.strip():
            raise RegistryError(f"entry {entry.get('name', '?')!r} is missing {field!r}")
        if value != value.strip():
            raise RegistryError(
                f"entry {entry.get('name', '?')!r} field {field!r} has surrounding whitespace"
            )

    name = entry["name"]
    if not NAME_PATTERN.match(name):
        raise RegistryError(
            f"plugin name {name!r} must match {NAME_PATTERN.pattern} "
            "(Zara PluginMetadata naming rules)"
        )
    if len(entry["version"]) > 64:
        raise RegistryError(f"plugin {name!r} version exceeds 64 characters")
    if not entry["api_version"] or len(entry["api_version"]) > 16:
        raise RegistryError(f"plugin {name!r} api_version must contain 1 to 16 characters")
    if entry["plugin_type"] not in ALLOWED_PLUGIN_TYPES:
        raise RegistryError(
            f"plugin {name!r} has plugin_type {entry['plugin_type']!r}; "
            f"allowed: {sorted(ALLOWED_PLUGIN_TYPES)}"
        )
    if len(entry["description"]) > 256:
        raise RegistryError(f"plugin {name!r} description exceeds 256 characters")
    if entry["license"] != GENERATED_FLAKE_LICENSE:
        raise RegistryError(
            f"plugin {name!r} license must match generated flake metadata "
            f"{GENERATED_FLAKE_LICENSE!r}"
        )

    dependencies = entry.get("python_dependencies", [])
    if (
        not isinstance(dependencies, list)
        or any(
            not isinstance(dependency, str)
            or not dependency.strip()
            or dependency != dependency.strip()
            for dependency in dependencies
        )
        or len(dependencies) != len(set(dependencies))
    ):
        raise RegistryError(
            f"plugin {name!r} python_dependencies must be a list of unique canonical non-empty strings"
        )

    nix = entry.get("nix")
    if not isinstance(nix, dict):
        raise RegistryError(f"plugin {name!r} is missing nix metadata")
    if nix.get("flake") != GENERATED_FLAKE_SOURCE:
        raise RegistryError(
            f"plugin {name!r} nix flake must match generated registry source "
            f"{GENERATED_FLAKE_SOURCE!r}"
        )
    if nix.get("package") != name:
        raise RegistryError(
            f"plugin {name!r} nix package must match the registry name"
        )
    if nix.get("aggregate") != "zara-plugins":
        raise RegistryError(
            f"plugin {name!r} nix aggregate must be 'zara-plugins'"
        )

    install = entry.get("install")
    if not isinstance(install, dict):
        raise RegistryError(f"plugin {name!r} is missing install metadata")
    install_nix = install.get("nix")
    if not isinstance(install_nix, str) or not install_nix.strip():
        raise RegistryError(f"plugin {name!r} is missing install.nix metadata")
    try:
        install_argv = shlex.split(install_nix)
    except ValueError as error:
        raise RegistryError(f"plugin {name!r} install.nix is invalid: {error}") from error
    expected_target = f"{GENERATED_FLAKE_SOURCE}#{name}"
    supported_install_commands = (
        ["nix", "build", expected_target],
        ["nix", "run", expected_target, "--", "install"],
    )
    if install_argv not in supported_install_commands:
        raise RegistryError(
            f"plugin {name!r} install.nix must be a supported generated install command "
            f"for {expected_target!r}"
        )

    plugin_dir = ROOT / entry["path"]
    if plugin_dir.parent != PLUGINS_DIR:
        raise RegistryError(
            f"plugin {name!r} path must live directly under plugins/ (got {entry['path']!r})"
        )
    if plugin_dir.name != name:
        raise RegistryError(
            f"plugin {name!r} directory name must match the plugin name "
            f"(got {plugin_dir.name!r})"
        )
    if not plugin_dir.is_dir():
        raise RegistryError(f"plugin {name!r} directory {entry['path']!r} does not exist")

    installer = plugin_dir / "tools" / name
    has_installer = installer.is_file()
    uses_run_installer = install_argv[1] == "run"
    if has_installer != uses_run_installer:
        raise RegistryError(
            f"plugin {name!r} install.nix does not match packaged installer layout"
        )
    if has_installer:
        expected_tool = f"python3 plugins/{name}/tools/{name} install"
        if install.get("tool") != expected_tool:
            raise RegistryError(
                f"plugin {name!r} install.tool does not match packaged installer layout"
            )
    elif "tool" in install:
        raise RegistryError(
            f"plugin {name!r} advertises install.tool without a packaged installer"
        )

    plugin_root = plugin_dir.resolve()
    entrypoint = (plugin_dir / entry["entrypoint"]).resolve()
    if not entrypoint.is_relative_to(plugin_root):
        raise RegistryError(f"plugin {name!r} entrypoint must stay inside its plugin directory")
    if not entrypoint.is_file():
        raise RegistryError(
            f"plugin {name!r} entrypoint {entry['entrypoint']!r} does not exist"
        )
    docs = entry.get("docs")
    if docs:
        docs_path = (ROOT / docs).resolve()
        if not docs_path.is_relative_to(plugin_root):
            raise RegistryError(f"plugin {name!r} docs must stay inside its plugin directory")
        if not docs_path.is_file():
            raise RegistryError(f"plugin {name!r} docs {docs!r} does not exist")

    tags = entry.get("tags", [])
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise RegistryError(f"plugin {name!r} tags must be a list of strings")
    if any(not tag.strip() or tag != tag.strip() for tag in tags):
        raise RegistryError(
            f"plugin {name!r} tags must be non-empty strings without surrounding whitespace"
        )
    if len(tags) != len(set(tags)):
        raise RegistryError(f"plugin {name!r} tags contain duplicates")

    if entry["plugin_type"] == "service":
        validate_service_entrypoint(entry, entrypoint)


def validate_service_entrypoint(entry: dict, entrypoint: Path) -> None:
    source = entrypoint.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(entrypoint))

    factories = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "create_plugin"
    ]
    if not factories:
        raise RegistryError(
            f"service plugin {entry['name']!r} entrypoint must define create_plugin()"
        )

    names = set()
    versions = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "PluginMetadata":
            continue
        for keyword in node.keywords:
            if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                names.add(keyword.value.value)
            if keyword.arg == "version" and isinstance(keyword.value, ast.Constant):
                versions.add(keyword.value.value)

    if names and entry["name"] not in names:
        raise RegistryError(
            f"plugin {entry['name']!r} registers PluginMetadata name(s) {sorted(names)!r} "
            "which does not match the registry entry"
        )
    if not versions:
        module_versions = {
            target.value.value
            for target in ast.walk(tree)
            if isinstance(target, ast.Assign)
            and len(target.targets) == 1
            and isinstance(target.targets[0], ast.Name)
            and "VERSION" in target.targets[0].id
            and isinstance(target.value, ast.Constant)
        }
        versions = module_versions
    if versions and entry["version"] not in versions:
        raise RegistryError(
            f"plugin {entry['name']!r} declares version(s) {sorted(map(str, versions))!r} "
            f"but the registry publishes {entry['version']!r}"
        )
    if not versions:
        raise RegistryError(
            f"plugin {entry['name']!r} version {entry['version']!r} could not be "
            "verified against the entrypoint source"
        )


def validate_catalog(document: dict) -> None:
    entries = document["plugins"]
    names = [entry.get("name") for entry in entries if isinstance(entry, dict)]
    if len(names) != len(set(names)):
        raise RegistryError("plugins.json contains duplicate plugin names")

    registered = {entry["path"] for entry in entries if isinstance(entry, dict)}
    on_disk = {f"plugins/{path.name}" for path in PLUGINS_DIR.iterdir() if path.is_dir()}
    unregistered = on_disk - registered
    if unregistered:
        raise RegistryError(
            f"plugin directories exist without a registry entry: {sorted(unregistered)}"
        )


def main() -> int:
    failures = []
    try:
        document = load_registry()
        for entry in document["plugins"]:
            failures.extend(_errors_from(lambda entry=entry: validate_entry(entry)))
        failures.extend(_errors_from(lambda: validate_catalog(document)))
    except RegistryError as error:
        failures.append(str(error))

    if failures:
        print("plugins.json is INVALID:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    count = len(document["plugins"])
    names = ", ".join(entry["name"] for entry in document["plugins"]) or "(empty)"
    print(f"plugins.json is valid: {count} plugin(s) registered [{names}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
