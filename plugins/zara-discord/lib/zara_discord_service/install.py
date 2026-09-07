from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InstallResult:
    plugin_entry: Path
    config_dir: Path


def _copy_writable(source: str, destination: str) -> str:
    shutil.copyfile(source, destination)
    os.chmod(destination, 0o644)
    return destination


def _ignore_bytecode(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name == "__pycache__" or name.endswith(".pyc")}


def _remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _recover_interrupted_publish(live: Path, backup: Path) -> None:
    if not backup.exists():
        return
    _remove_path(live)
    os.replace(backup, live)


def _publish_install(
    *,
    staging: Path,
    library_dir: Path,
    wrapper_staging: Path,
    plugin_entry: Path,
) -> None:
    library_backup = library_dir.with_name(".lib.backup")
    wrapper_backup = plugin_entry.with_name(".zara_discord.py.backup")

    # A backup can be the only last-known-good copy after process death. Roll
    # any interrupted publication back before starting a new transaction.
    _recover_interrupted_publish(library_dir, library_backup)
    _recover_interrupted_publish(plugin_entry, wrapper_backup)

    library_backed_up = False
    wrapper_backed_up = False
    library_published = False
    wrapper_published = False
    try:
        if library_dir.exists():
            os.replace(library_dir, library_backup)
            library_backed_up = True
        os.replace(staging, library_dir)
        library_published = True

        if plugin_entry.exists():
            os.replace(plugin_entry, wrapper_backup)
            wrapper_backed_up = True
        os.replace(wrapper_staging, plugin_entry)
        wrapper_published = True
    except BaseException:
        if wrapper_published:
            _remove_path(plugin_entry)
        if wrapper_backed_up:
            os.replace(wrapper_backup, plugin_entry)
        if library_published:
            _remove_path(library_dir)
        if library_backed_up:
            os.replace(library_backup, library_dir)
        _remove_path(staging)
        _remove_path(wrapper_staging)
        _remove_path(library_backup)
        _remove_path(wrapper_backup)
        raise

    _remove_path(library_backup)
    _remove_path(wrapper_backup)


def install(
    *,
    home: Path | None = None,
    xdg_config_home: Path | None = None,
) -> InstallResult:
    resolved_home = home or Path.home()
    resolved_xdg = xdg_config_home or Path(
        os.environ.get("XDG_CONFIG_HOME", resolved_home / ".config")
    )
    config_dir = resolved_xdg / "zarathushtra" / "plugins" / "zara-discord"
    library_dir = config_dir / "lib"
    plugin_dir = resolved_home / ".zarathushtra" / "plugins"
    plugin_entry = plugin_dir / "zara_discord.py"

    config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(config_dir, 0o700)
    plugin_dir.mkdir(parents=True, exist_ok=True)

    staging = config_dir / ".lib.tmp"
    wrapper_staging = plugin_entry.with_name(".zara_discord.py.tmp")
    _remove_path(staging)
    _remove_path(wrapper_staging)
    staging.mkdir()
    source_package = Path(__file__).resolve().parent
    plugin_root = source_package.parents[1]
    shutil.copytree(
        source_package,
        staging / "zara_discord_service",
        copy_function=_copy_writable,
        ignore=_ignore_bytecode,
    )

    discord_spec = importlib.util.find_spec("discord")
    if discord_spec is None or discord_spec.submodule_search_locations is None:
        raise RuntimeError("discord.py is not installed in the installer environment")
    discord_source = Path(next(iter(discord_spec.submodule_search_locations)))
    shutil.copytree(
        discord_source,
        staging / "discord",
        copy_function=_copy_writable,
        ignore=_ignore_bytecode,
    )
    audioop_spec = importlib.util.find_spec("audioop")
    if audioop_spec is None or audioop_spec.submodule_search_locations is None:
        raise RuntimeError("Python audioop compatibility package is not installed")
    audioop_source = Path(next(iter(audioop_spec.submodule_search_locations)))
    shutil.copytree(
        audioop_source,
        staging / "audioop",
        copy_function=_copy_writable,
        ignore=_ignore_bytecode,
    )
    for path in staging.rglob("*"):
        os.chmod(path, 0o755 if path.is_dir() else 0o644)

    wrapper_source = plugin_root / "zara-plugin" / "zara_discord.py"
    shutil.copy2(wrapper_source, wrapper_staging)
    _publish_install(
        staging=staging,
        library_dir=library_dir,
        wrapper_staging=wrapper_staging,
        plugin_entry=plugin_entry,
    )

    readme = config_dir / "README.txt"
    readme.write_text(
        "Zara Discord plugin configuration\n\n"
        "Set ZARA_DISCORD_TOKEN before starting Zara, or place the token in:\n"
        f"  {config_dir / 'token'}\n"
        "and run chmod 600 on that file. Guild policy is written to settings.json\n"
        "by Discord slash commands.\n",
        encoding="utf-8",
    )
    return InstallResult(plugin_entry=plugin_entry, config_dir=config_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install the Zara Discord service plugin")
    parser.add_argument("command", nargs="?", default="install", choices=("install",))
    parser.parse_args()
    result = install()
    print(f"Installed Zara plugin entry: {result.plugin_entry}")
    print(f"Discord plugin configuration: {result.config_dir}")
