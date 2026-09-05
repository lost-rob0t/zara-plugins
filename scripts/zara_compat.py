#!/usr/bin/env python3
"""Validate every published plugin against one exact Zara source tree."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:
    from .zara_compat_runtime import (
        CompatibilityRuntime,
        exercise_service_lifecycle,
        fake_dependency_environment,
        temporary_runtime_environment,
    )
except ImportError:
    from zara_compat_runtime import (
        CompatibilityRuntime,
        exercise_service_lifecycle,
        fake_dependency_environment,
        temporary_runtime_environment,
    )


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
    for field in ("name", "version", "api_version", "plugin_type", "description"):
        expected = str(entry.get(field, ""))
        observed = str(getattr(actual, field, ""))
        if observed != expected:
            raise CompatibilityError(
                f"{name}: metadata {field} mismatch: expected {expected!r}, got {observed!r}"
            )


def require_tool_names(name: str, tools: tuple[Any, ...] | list[Any], seen: dict[str, str]) -> None:
    local: set[str] = set()
    for tool in tools:
        tool_name = str(getattr(tool, "name", ""))
        if not tool_name.strip():
            raise CompatibilityError(f"{name}: tool has an empty name")
        if tool_name != tool_name.strip():
            raise CompatibilityError(
                f"{name}: tool name {tool_name!r} has surrounding whitespace"
            )
        if tool_name in local:
            raise CompatibilityError(f"{name}: duplicate tool name {tool_name!r}")
        owner = seen.get(tool_name)
        if owner is not None:
            raise CompatibilityError(
                f"{name}: tool name {tool_name!r} collides with published plugin {owner}"
            )
        local.add(tool_name)
    for tool_name in local:
        seen[tool_name] = name


def require_search_path_discovery(
    expected: dict[Path, str],
    iter_plugin_files,
    search_path: Path = Path("."),
) -> None:
    discovered = {Path(path).resolve() for path in iter_plugin_files((search_path,))}
    for entrypoint, name in expected.items():
        if entrypoint.resolve() not in discovered:
            raise CompatibilityError(
                f"{name}: packaged entrypoint is not discoverable through Zara plugin search path"
            )


def plugin_paths(
    root: Path,
    entry: dict[str, Any],
    *,
    runtime_root: Path | None = None,
) -> tuple[Path, Path]:
    if runtime_root is not None:
        plugin_runtime = runtime_root / str(entry["name"])
        return plugin_runtime / "entrypoint.py", plugin_runtime / "lib"
    plugin_source = root / str(entry["path"])
    return plugin_source / str(entry["entrypoint"]), plugin_source / "lib"


def _is_plugin_library(path: str, root: Path, runtime_root: Path | None) -> bool:
    try:
        candidate = Path(path).resolve()
    except (OSError, RuntimeError):
        return False
    if candidate.name != "lib":
        return False
    if runtime_root is not None:
        return candidate.parent.parent == runtime_root.resolve()
    return candidate.parent.parent == (root.resolve() / "plugins")


@contextmanager
def plugin_import_environment(
    root: Path,
    entry: dict[str, Any],
    *,
    runtime_root: Path | None = None,
):
    _, library = plugin_paths(root, entry, runtime_root=runtime_root)
    previous_path = list(sys.path)
    previous_modules = set(sys.modules)
    filtered = [
        path
        for path in previous_path
        if not _is_plugin_library(path, root, runtime_root)
    ]
    sys.path[:] = [str(library), *filtered]
    try:
        yield
    finally:
        sys.path[:] = previous_path
        for module_name in tuple(set(sys.modules) - previous_modules):
            sys.modules.pop(module_name, None)


def _load_runtime_contracts(zara_source: Path):
    sys.path.insert(0, str(zara_source))
    try:
        from langchain_core.tools import BaseTool
        from zara.plugins import PLUGIN_API_VERSION, PluginMetadata, ServicePlugin
        from zara.plugins.loader import iter_plugin_files, load_plugin_module
    except Exception as error:
        raise CompatibilityError(
            f"could not import pinned Zara plugin API: {type(error).__name__}: {error}"
        ) from error
    return (
        BaseTool,
        PLUGIN_API_VERSION,
        PluginMetadata,
        ServicePlugin,
        iter_plugin_files,
        load_plugin_module,
    )


def _qualified_type(value: object) -> str:
    kind = type(value)
    return f"{kind.__module__}.{kind.__qualname__}"


def check_registry(
    root: Path,
    zara_source: Path,
    *,
    runtime_root: Path | None = None,
) -> list[str]:
    root = root.resolve()
    runtime_root = runtime_root.resolve() if runtime_root is not None else None
    zara_source = validate_zara_source(zara_source)
    entries = load_registry(root / "plugins.json")
    (
        BaseTool,
        api_version,
        PluginMetadata,
        ServicePlugin,
        iter_plugin_files,
        load_plugin_module,
    ) = _load_runtime_contracts(zara_source)

    failures: list[str] = []
    seen_tool_names: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="zara-plugin-compat-") as temporary_home:
        home = Path(temporary_home)
        search_path = home / ".zarathushtra" / "plugins"
        search_path.mkdir(parents=True, exist_ok=True)
        expected_discovery: dict[Path, str] = {}
        with temporary_runtime_environment(home):
            for entry in entries:
                name = str(entry.get("name", "?"))
                if str(entry.get("api_version", "")) != api_version:
                    failures.append(
                        f"{name}: registry API {entry.get('api_version')!r} is incompatible with Zara {api_version!r}"
                    )
                    continue
                entrypoint, _ = plugin_paths(root, entry, runtime_root=runtime_root)
                if not entrypoint.is_file():
                    failures.append(f"{name}: installed entrypoint is missing: {entrypoint}")
                    continue
                discovery_link = search_path / f"{name}.py"
                try:
                    discovery_link.symlink_to(entrypoint.resolve())
                    expected_discovery[entrypoint.resolve()] = name
                except OSError as error:
                    failures.append(
                        f"{name}: could not project packaged entrypoint into Zara plugin search path: {error}"
                    )
                    continue
                try:
                    with plugin_import_environment(root, entry, runtime_root=runtime_root):
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
                                expected = f"{PluginMetadata.__module__}.{PluginMetadata.__qualname__}"
                                observed = _qualified_type(metadata)
                                raise CompatibilityError(
                                    "service metadata is not Zara PluginMetadata "
                                    f"(expected {expected}, observed {observed})"
                                )
                            require_metadata(entry, metadata)
                            tools = tuple(instance.tools())
                            invalid = [type(tool).__name__ for tool in tools if not isinstance(tool, BaseTool)]
                            if invalid:
                                raise CompatibilityError(
                                    f"tools() returned non-BaseTool values: {', '.join(invalid)}"
                                )
                            require_tool_names(name, tools, seen_tool_names)
                            with fake_dependency_environment(name):
                                exercise_service_lifecycle(instance, CompatibilityRuntime(name))
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
                                require_tool_names(name, tools, seen_tool_names)
                except Exception as error:
                    failures.append(f"{name}: {type(error).__name__}: {error}")
            try:
                require_search_path_discovery(
                    expected_discovery,
                    iter_plugin_files,
                    search_path,
                )
            except CompatibilityError as error:
                failures.append(str(error))
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--zara-source", type=Path, required=True)
    parser.add_argument(
        "--runtime-root",
        type=Path,
        help="Load packaged entrypoints from share/zara/runtime instead of the source tree.",
    )
    arguments = parser.parse_args(argv)

    failures = check_registry(
        arguments.root,
        arguments.zara_source,
        runtime_root=arguments.runtime_root,
    )
    if failures:
        print("Zara plugin compatibility is INVALID:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    entries = load_registry(arguments.root / "plugins.json")
    names = ", ".join(str(entry["name"]) for entry in entries)
    location = "installed runtime" if arguments.runtime_root is not None else "source tree"
    print(
        f"Zara plugin compatibility is valid from {location}: "
        f"{len(entries)} plugin(s) [{names}]"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
