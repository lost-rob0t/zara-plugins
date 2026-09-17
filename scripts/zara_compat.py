#!/usr/bin/env python3
"""Validate every published plugin against one exact Zara source tree."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
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
        invoke_compatibility_call,
        temporary_runtime_environment,
    )
except ImportError:
    from zara_compat_runtime import (
        CompatibilityRuntime,
        exercise_service_lifecycle,
        fake_dependency_environment,
        invoke_compatibility_call,
        temporary_runtime_environment,
    )


class CompatibilityError(RuntimeError):
    pass


_MISSING = object()
_MAX_WORKER_RESULT_BYTES = 64 * 1024
_WORKER_STATUSES = {"passed", "contract-error"}


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


def read_compatibility_attribute(
    value: Any,
    name: str,
    default: Any = None,
    *,
    timeout: float = 5.0,
) -> Any:
    return invoke_compatibility_call(
        lambda: getattr(value, name, default),
        timeout=timeout,
    )


def require_metadata(
    entry: dict[str, Any],
    actual: Any,
    *,
    timeout: float = 5.0,
) -> None:
    name = str(entry.get("name", "?"))
    for field in ("name", "version", "api_version", "plugin_type", "description"):
        expected = str(entry.get(field, ""))
        observed = str(
            read_compatibility_attribute(actual, field, "", timeout=timeout)
        )
        if observed != expected:
            raise CompatibilityError(
                f"{name}: metadata {field} mismatch: expected {expected!r}, got {observed!r}"
            )


def require_service_activation_contract(
    name: str,
    instance: Any,
    *,
    timeout: float = 5.0,
) -> None:
    enabled_by_default = read_compatibility_attribute(
        instance,
        "enabled_by_default",
        True,
        timeout=timeout,
    )
    if not isinstance(enabled_by_default, bool):
        raise CompatibilityError(f"{name}: enabled_by_default must be a boolean")


def construct_service_plugin(factory: Any, *, timeout: float = 5.0) -> Any:
    return invoke_compatibility_call(factory, timeout=timeout)


def collect_service_tools(instance: Any, *, timeout: float = 5.0) -> tuple[Any, ...]:
    method = read_compatibility_attribute(instance, "tools", None, timeout=timeout)
    if not callable(method):
        return ()
    return tuple(invoke_compatibility_call(method, timeout=timeout))


def require_tool_names(
    name: str,
    tools: tuple[Any, ...] | list[Any],
    seen: dict[str, str],
    *,
    timeout: float = 5.0,
) -> None:
    local: set[str] = set()
    for tool in tools:
        tool_name = str(
            read_compatibility_attribute(tool, "name", "", timeout=timeout)
        )
        _require_one_tool_name(name, tool_name, local, seen)
    for tool_name in local:
        seen[tool_name] = name


def _require_one_tool_name(
    name: str,
    tool_name: str,
    local: set[str],
    seen: dict[str, str],
) -> None:
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


def require_reported_tool_names(
    name: str,
    tool_names: list[str],
    seen: dict[str, str],
) -> None:
    local: set[str] = set()
    for tool_name in tool_names:
        if not isinstance(tool_name, str):
            raise CompatibilityError(f"{name}: compatibility worker returned a non-string tool name")
        _require_one_tool_name(name, tool_name, local, seen)
    for tool_name in local:
        seen[tool_name] = name


def require_legacy_tool_entrypoint(
    name: str,
    module: Any,
    BaseTool: type[Any],
    seen_tool_names: dict[str, str],
    *,
    timeout: float = 5.0,
) -> tuple[Any, ...]:
    entrypoint_name = "register_tools"
    entrypoint = read_compatibility_attribute(
        module,
        entrypoint_name,
        _MISSING,
        timeout=timeout,
    )
    if entrypoint is _MISSING:
        entrypoint_name = "register_skills"
        entrypoint = read_compatibility_attribute(
            module,
            entrypoint_name,
            _MISSING,
            timeout=timeout,
        )
    if entrypoint is _MISSING:
        raise CompatibilityError(
            "tool entrypoint defines neither register_tools() nor register_skills()"
        )
    if not callable(entrypoint):
        raise CompatibilityError(f"{name}: {entrypoint_name} exists but is not callable")

    tools = tuple(invoke_compatibility_call(entrypoint, None, timeout=timeout))
    invalid = [type(tool).__name__ for tool in tools if not isinstance(tool, BaseTool)]
    if invalid:
        raise CompatibilityError(
            f"{name}: {entrypoint_name}() returned non-BaseTool values: {', '.join(invalid)}"
        )
    require_tool_names(name, tools, seen_tool_names, timeout=timeout)
    return tools


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
    source_plugins = root.resolve() / "plugins"
    if candidate.parent.parent == source_plugins:
        return True
    return runtime_root is not None and candidate.parent.parent == runtime_root.resolve()


@contextmanager
def plugin_import_environment(
    root: Path,
    entry: dict[str, Any],
    *,
    runtime_root: Path | None = None,
):
    """Legacy unit-test helper; production compatibility imports happen in child processes."""
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


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.kill()


def run_compatibility_process(
    command: list[str],
    result_path: Path,
    *,
    timeout: float,
) -> dict[str, Any]:
    """Run one compatibility worker behind a hard process/crash boundary."""
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.unlink(missing_ok=True)
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=(os.name == "posix"),
    )
    try:
        return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
        process.wait(timeout=2.0)
        return {"status": "timeout"}

    if return_code < 0:
        number = -return_code
        try:
            signal_name = signal.Signals(number).name
        except ValueError:
            signal_name = f"SIG{number}"
        return {"status": "crashed", "signal": signal_name}

    if not result_path.is_file():
        return {"status": "invalid-result", "reason": f"worker exited {return_code} without a result"}
    try:
        size = result_path.stat().st_size
    except OSError as error:
        return {"status": "invalid-result", "reason": f"could not stat worker result: {type(error).__name__}"}
    if size > _MAX_WORKER_RESULT_BYTES:
        return {"status": "invalid-result", "reason": "worker result is too large"}
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {"status": "invalid-result", "reason": f"worker result is not valid JSON: {type(error).__name__}"}
    if not isinstance(result, dict) or result.get("status") not in _WORKER_STATUSES:
        return {"status": "invalid-result", "reason": "worker result has an invalid status"}
    if result["status"] == "passed":
        tool_names = result.get("tool_names")
        if not isinstance(tool_names, list) or not all(isinstance(item, str) for item in tool_names):
            return {"status": "invalid-result", "reason": "passed worker result has invalid tool_names"}
    elif not isinstance(result.get("error"), str):
        return {"status": "invalid-result", "reason": "contract-error result has no bounded error"}
    return result


def run_plugin_compatibility(
    root: Path,
    zara_source: Path,
    entry: dict[str, Any],
    result_path: Path,
    *,
    runtime_root: Path | None = None,
    call_timeout: float = 5.0,
) -> dict[str, Any]:
    worker = Path(__file__).with_name("zara_compat_worker.py")
    command = [
        sys.executable,
        str(worker),
        "--root",
        str(root),
        "--zara-source",
        str(zara_source),
        "--entry-json",
        json.dumps(entry, separators=(",", ":")),
        "--result",
        str(result_path),
    ]
    if runtime_root is not None:
        command.extend(("--runtime-root", str(runtime_root)))
    return run_compatibility_process(
        command,
        result_path,
        timeout=max(0.1, call_timeout * 6.0),
    )


def check_registry(
    root: Path,
    zara_source: Path,
    *,
    runtime_root: Path | None = None,
    call_timeout: float = 5.0,
) -> list[str]:
    root = root.resolve()
    runtime_root = runtime_root.resolve() if runtime_root is not None else None
    zara_source = validate_zara_source(zara_source)
    entries = load_registry(root / "plugins.json")
    _, api_version, _, _, iter_plugin_files, _ = _load_runtime_contracts(zara_source)

    failures: list[str] = []
    seen_tool_names: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="zara-plugin-compat-") as temporary_home:
        home = Path(temporary_home)
        search_path = home / ".zarathushtra" / "plugins"
        result_root = home / "compat-results"
        search_path.mkdir(parents=True, exist_ok=True)
        expected_discovery: dict[Path, str] = {}
        with temporary_runtime_environment(home):
            for index, entry in enumerate(entries):
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

                result = run_plugin_compatibility(
                    root,
                    zara_source,
                    entry,
                    result_root / f"{index:04d}.json",
                    runtime_root=runtime_root,
                    call_timeout=call_timeout,
                )
                status = result.get("status")
                if status == "passed":
                    try:
                        require_reported_tool_names(
                            name,
                            result["tool_names"],
                            seen_tool_names,
                        )
                    except CompatibilityError as error:
                        failures.append(str(error))
                elif status == "contract-error":
                    failures.append(f"{name}: {result['error']}")
                elif status == "crashed":
                    failures.append(f"{name}: compatibility worker crashed ({result.get('signal', 'unknown signal')})")
                elif status == "timeout":
                    failures.append(f"{name}: TimeoutError: compatibility worker exceeded its process deadline")
                else:
                    failures.append(f"{name}: invalid compatibility worker result: {result.get('reason', 'unknown error')}")

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
