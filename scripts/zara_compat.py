#!/usr/bin/env python3
"""Validate every published plugin against one exact Zara source tree."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


class CompatibilityError(RuntimeError):
    pass


def load_registry(path: Path) -> list[dict[str, Any]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CompatibilityError(f"could not read plugin registry: {error}") from error
    entries = document.get("plugins")
    if not isinstance(entries, list):
        raise CompatibilityError("plugin registry does not contain a plugins array")
    return entries


def validate_zara_source(path: Path) -> Path:
    source = path.resolve()
    api = source / "zara" / "plugins" / "api.py"
    manager = source / "zara" / "plugins" / "manager.py"
    loader = source / "zara" / "plugins" / "loader.py"
    if not api.is_file() or not manager.is_file() or not loader.is_file():
        raise CompatibilityError(
            f"Zara source {source} does not contain the zara.plugins API source"
        )
    return source


def require_metadata(entry: dict[str, Any], actual: Any) -> None:
    name = str(entry.get("name", "?"))
    for field in ("name", "version", "api_version", "plugin_type"):
        expected = str(entry.get(field, ""))
        observed = str(getattr(actual, field, ""))
        if observed != expected:
            raise CompatibilityError(
                f"{name}: metadata {field} mismatch: expected {expected!r}, got {observed!r}"
            )


def _load_runtime_contracts(zara_source: Path):
    sys.path.insert(0, str(zara_source))
    try:
        from langchain_core.tools import BaseTool
        from zara.plugins import PLUGIN_API_VERSION, PluginMetadata, ServicePlugin
        from zara.plugins.loader import load_plugin_module
    except Exception as error:
        raise CompatibilityError(
            f"could not import pinned Zara plugin API: {type(error).__name__}: {error}"
        ) from error
    return BaseTool, PLUGIN_API_VERSION, PluginMetadata, ServicePlugin, load_plugin_module


def _prepare_plugin_imports(root: Path, entries: list[dict[str, Any]]) -> None:
    for entry in reversed(entries):
        library = root / str(entry["path"]) / "lib"
        if library.is_dir():
            sys.path.insert(0, str(library))


def check_registry(root: Path, zara_source: Path) -> list[str]:
    root = root.resolve()
    zara_source = validate_zara_source(zara_source)
    entries = load_registry(root / "plugins.json")
    _prepare_plugin_imports(root, entries)
    BaseTool, api_version, PluginMetadata, ServicePlugin, load_plugin_module = (
        _load_runtime_contracts(zara_source)
    )

    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="zara-plugin-compat-") as temporary_home:
        previous_home = os.environ.get("HOME")
        previous_xdg = os.environ.get("XDG_CONFIG_HOME")
        os.environ["HOME"] = temporary_home
        os.environ["XDG_CONFIG_HOME"] = str(Path(temporary_home) / ".config")
        try:
            for entry in entries:
                name = str(entry.get("name", "?"))
                if str(entry.get("api_version", "")) != api_version:
                    failures.append(
                        f"{name}: registry API {entry.get('api_version')!r} is incompatible with Zara {api_version!r}"
                    )
                    continue
                entrypoint = root / str(entry["path"]) / str(entry["entrypoint"])
                try:
                    module = load_plugin_module(entrypoint)
                    if entry.get("plugin_type") == "service":
                        factory = getattr(module, "create_plugin", None)
                        if not callable(factory):
                            raise CompatibilityError("service entrypoint has no create_plugin()")
                        instance = factory()
                        if not isinstance(instance, ServicePlugin):
                            raise CompatibilityError(
                                f"create_plugin() returned {type(instance).__name__}, not Zara ServicePlugin"
                            )
                        metadata = getattr(instance, "metadata", None)
                        if not isinstance(metadata, PluginMetadata):
                            raise CompatibilityError("service metadata is not Zara PluginMetadata")
                        require_metadata(entry, metadata)
                        tools = tuple(instance.tools())
                        invalid = [type(tool).__name__ for tool in tools if not isinstance(tool, BaseTool)]
                        if invalid:
                            raise CompatibilityError(
                                f"tools() returned non-BaseTool values: {', '.join(invalid)}"
                            )
                    else:
                        register_tools = getattr(module, "register_tools", None)
                        register_skills = getattr(module, "register_skills", None)
                        if not callable(register_tools) and not callable(register_skills):
                            raise CompatibilityError(
                                "tool entrypoint defines neither register_tools() nor register_skills()"
                            )
                        if callable(register_tools):
                            tools = tuple(register_tools())
                            invalid = [
                                type(tool).__name__
                                for tool in tools
                                if not isinstance(tool, BaseTool)
                            ]
                            if invalid:
                                raise CompatibilityError(
                                    f"register_tools() returned non-BaseTool values: {', '.join(invalid)}"
                                )
                except Exception as error:
                    failures.append(f"{name}: {type(error).__name__}: {error}")
        finally:
            if previous_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = previous_home
            if previous_xdg is None:
                os.environ.pop("XDG_CONFIG_HOME", None)
            else:
                os.environ["XDG_CONFIG_HOME"] = previous_xdg
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--zara-source", type=Path, required=True)
    arguments = parser.parse_args(argv)

    failures = check_registry(arguments.root, arguments.zara_source)
    if failures:
        print("Zara plugin compatibility is INVALID:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    entries = load_registry(arguments.root / "plugins.json")
    names = ", ".join(str(entry["name"]) for entry in entries)
    print(f"Zara plugin compatibility is valid: {len(entries)} plugin(s) [{names}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
