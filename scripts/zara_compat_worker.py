#!/usr/bin/env python3
"""Exercise exactly one Zara plugin in an isolated compatibility process."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any

from zara_compat_runtime import CompatibilityRuntime, fake_dependency_environment


_MAX_ERROR_CHARS = 1024
_SENSITIVE_ENV_MARKERS = ("TOKEN", "KEY", "SECRET", "PASSWORD", "CREDENTIAL")
_MISSING = object()


def _plugin_paths(
    root: Path,
    entry: dict[str, Any],
    runtime_root: Path | None,
) -> tuple[Path, Path]:
    if runtime_root is not None:
        plugin_runtime = runtime_root / str(entry["name"])
        return plugin_runtime / "entrypoint.py", plugin_runtime / "lib"
    plugin_source = root / str(entry["path"])
    return plugin_source / str(entry["entrypoint"]), plugin_source / "lib"


def _call(method, *args):
    result = method(*args)
    if inspect.isawaitable(result):
        return asyncio.run(result)
    return result


def _safe_error(error: Exception) -> str:
    text = str(error).replace("\r", " ").replace("\n", " ")
    for name, value in os.environ.items():
        if not value or len(value) < 4:
            continue
        upper = name.upper()
        if any(marker in upper for marker in _SENSITIVE_ENV_MARKERS):
            text = text.replace(value, "[REDACTED]")
    text = text[:_MAX_ERROR_CHARS]
    return f"{type(error).__name__}: {text}"


def _write_result(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _validate_metadata(entry: dict[str, Any], metadata: Any) -> None:
    name = str(entry.get("name", "?"))
    for field in ("name", "version", "api_version", "plugin_type", "description"):
        expected = str(entry.get(field, ""))
        observed = str(getattr(metadata, field, ""))
        if observed != expected:
            raise RuntimeError(
                f"{name}: metadata {field} mismatch: expected {expected!r}, got {observed!r}"
            )


def _validate_tool_names(name: str, tools: tuple[Any, ...]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for tool in tools:
        tool_name = str(getattr(tool, "name", ""))
        if not tool_name.strip():
            raise RuntimeError(f"{name}: tool has an empty name")
        if tool_name != tool_name.strip():
            raise RuntimeError(
                f"{name}: tool name {tool_name!r} has surrounding whitespace"
            )
        if tool_name in seen:
            raise RuntimeError(f"{name}: duplicate tool name {tool_name!r}")
        seen.add(tool_name)
        names.append(tool_name)
    return names


def _exercise_lifecycle(instance: Any, runtime: CompatibilityRuntime) -> None:
    started = False
    try:
        started = True
        _call(instance.start, runtime)
    finally:
        try:
            if started:
                _call(instance.stop)
        finally:
            runtime._shutdown()


def exercise_plugin(
    root: Path,
    zara_source: Path,
    entry: dict[str, Any],
    *,
    runtime_root: Path | None,
) -> dict[str, Any]:
    name = str(entry.get("name", "?"))
    entrypoint, library = _plugin_paths(root, entry, runtime_root)
    if not entrypoint.is_file():
        raise RuntimeError(f"{name}: installed entrypoint is missing: {entrypoint}")

    sys.path.insert(0, str(zara_source))
    sys.path.insert(0, str(library))

    from langchain_core.tools import BaseTool
    from zara.plugins import PLUGIN_API_VERSION, PluginMetadata, ServicePlugin
    from zara.plugins.loader import load_plugin_module

    if str(entry.get("api_version", "")) != PLUGIN_API_VERSION:
        raise RuntimeError(
            f"{name}: registry API {entry.get('api_version')!r} is incompatible with Zara {PLUGIN_API_VERSION!r}"
        )

    module = load_plugin_module(entrypoint)
    if entry.get("plugin_type") == "service":
        factory = getattr(module, "create_plugin", _MISSING)
        if factory is _MISSING or not callable(factory):
            raise RuntimeError("service entrypoint has no create_plugin()")
        instance = _call(factory)
        if not isinstance(instance, ServicePlugin):
            raise RuntimeError(
                f"create_plugin() returned {type(instance).__name__}, not Zara ServicePlugin"
            )
        metadata = getattr(instance, "metadata", None)
        if not isinstance(metadata, PluginMetadata):
            expected = f"{PluginMetadata.__module__}.{PluginMetadata.__qualname__}"
            observed_type = type(metadata)
            observed = f"{observed_type.__module__}.{observed_type.__qualname__}"
            raise RuntimeError(
                "service metadata is not Zara PluginMetadata "
                f"(expected {expected}, observed {observed})"
            )
        _validate_metadata(entry, metadata)
        enabled = getattr(instance, "enabled_by_default", True)
        if not isinstance(enabled, bool):
            raise RuntimeError(f"{name}: enabled_by_default must be a boolean")
        tools_method = getattr(instance, "tools", None)
        tools = tuple(_call(tools_method)) if callable(tools_method) else ()
        invalid = [type(tool).__name__ for tool in tools if not isinstance(tool, BaseTool)]
        if invalid:
            raise RuntimeError(
                f"tools() returned non-BaseTool values: {', '.join(invalid)}"
            )
        tool_names = _validate_tool_names(name, tools)
        with fake_dependency_environment(name):
            _exercise_lifecycle(instance, CompatibilityRuntime(name))
        return {"status": "passed", "tool_names": tool_names}

    entrypoint_name = "register_tools"
    legacy = getattr(module, entrypoint_name, _MISSING)
    if legacy is _MISSING:
        entrypoint_name = "register_skills"
        legacy = getattr(module, entrypoint_name, _MISSING)
    if legacy is _MISSING:
        raise RuntimeError(
            "tool entrypoint defines neither register_tools() nor register_skills()"
        )
    if not callable(legacy):
        raise RuntimeError(f"{name}: {entrypoint_name} exists but is not callable")
    tools = tuple(_call(legacy, None))
    invalid = [type(tool).__name__ for tool in tools if not isinstance(tool, BaseTool)]
    if invalid:
        raise RuntimeError(
            f"{name}: {entrypoint_name}() returned non-BaseTool values: {', '.join(invalid)}"
        )
    return {"status": "passed", "tool_names": _validate_tool_names(name, tools)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--zara-source", type=Path, required=True)
    parser.add_argument("--entry-json", required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path)
    arguments = parser.parse_args(argv)

    try:
        entry = json.loads(arguments.entry_json)
        if not isinstance(entry, dict):
            raise ValueError("entry must be an object")
        result = exercise_plugin(
            arguments.root.resolve(),
            arguments.zara_source.resolve(),
            entry,
            runtime_root=(
                arguments.runtime_root.resolve()
                if arguments.runtime_root is not None
                else None
            ),
        )
    except Exception as error:
        result = {"status": "contract-error", "error": _safe_error(error)}

    _write_result(arguments.result, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
