from __future__ import annotations

import argparse
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InstallResult:
    plugin_entry: Path
    config_dir: Path
    sync_script: Path


def _copy_writable(source: str, destination: str) -> str:
    shutil.copyfile(source, destination)
    os.chmod(destination, 0o644)
    return destination


def _ignore_bytecode(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name == "__pycache__" or name.endswith(".pyc")}


def install(
    *,
    home: Path | None = None,
    xdg_config_home: Path | None = None,
) -> InstallResult:
    resolved_home = home or Path.home()
    resolved_xdg = xdg_config_home or Path(
        os.environ.get("XDG_CONFIG_HOME", resolved_home / ".config")
    )
    config_dir = resolved_xdg / "zarathushtra" / "plugins" / "zara-org-todos"
    library_dir = config_dir / "lib"
    libexec_dir = config_dir / "libexec"
    plugin_dir = resolved_home / ".zarathushtra" / "plugins"
    plugin_entry = plugin_dir / "zara_org_todos.py"

    config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(config_dir, 0o700)
    plugin_dir.mkdir(parents=True, exist_ok=True)

    source_package = Path(__file__).resolve().parent
    plugin_root = source_package.parents[1]
    staging = config_dir / ".lib.tmp"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    shutil.copytree(
        source_package,
        staging / "zara_org_todos_service",
        copy_function=_copy_writable,
        ignore=_ignore_bytecode,
    )
    if library_dir.exists():
        shutil.rmtree(library_dir)
    staging.replace(library_dir)

    libexec_dir.mkdir(parents=True, exist_ok=True)
    sync_source = plugin_root / "libexec" / "gpt-todos-sync"
    sync_script = libexec_dir / "gpt-todos-sync"
    shutil.copy2(sync_source, sync_script)
    os.chmod(sync_script, 0o755)

    wrapper_source = plugin_root / "zara-plugin" / "zara_org_todos.py"
    shutil.copy2(wrapper_source, plugin_entry)
    readme = config_dir / "README.txt"
    readme.write_text(
        "Zara Org Todos plugin\n\n"
        "Defaults:\n"
        "  repo: ~/Documents/gpt-todos\n"
        "  agenda: ~/Documents/Notes/org/agenda\n"
        "  interval: 300 seconds\n\n"
        "Environment overrides use the ZARA_ORG_TODOS_* variables documented in the plugin README.\n",
        encoding="utf-8",
    )
    return InstallResult(
        plugin_entry=plugin_entry,
        config_dir=config_dir,
        sync_script=sync_script,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Install the Zara Org Todos service plugin")
    parser.add_argument("command", nargs="?", default="install", choices=("install",))
    parser.parse_args()
    result = install()
    print(f"Installed Zara plugin entry: {result.plugin_entry}")
    print(f"Org Todos plugin configuration: {result.config_dir}")
    print(f"Bundled sync engine: {result.sync_script}")
