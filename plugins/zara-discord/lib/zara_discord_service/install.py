from __future__ import annotations

import argparse
import importlib.util
import json
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


def _restore_component(*, live: Path, backup: Path, existed: bool) -> None:
    if existed:
        if backup.exists():
            _remove_path(live)
            os.replace(backup, live)
        return
    _remove_path(live)
    _remove_path(backup)


def _recover_interrupted_publish(
    *,
    library_dir: Path,
    library_backup: Path,
    plugin_entry: Path,
    wrapper_backup: Path,
    transaction_marker: Path,
) -> None:
    if transaction_marker.exists():
        state = json.loads(transaction_marker.read_text(encoding="utf-8"))
        _restore_component(
            live=library_dir,
            backup=library_backup,
            existed=bool(state["library_existed"]),
        )
        _restore_component(
            live=plugin_entry,
            backup=wrapper_backup,
            existed=bool(state["wrapper_existed"]),
        )
        _remove_path(library_backup)
        _remove_path(wrapper_backup)
        _remove_path(transaction_marker)
        return

    # Legacy fixed backups predate the transaction marker. A missing live path
    # proves publication was interrupted before replacement; a live path means
    # the backup can only be treated safely as stale cleanup residue.
    for live, backup in (
        (library_dir, library_backup),
        (plugin_entry, wrapper_backup),
    ):
        if not backup.exists():
            continue
        if live.exists():
            _remove_path(backup)
        else:
            os.replace(backup, live)


def _write_transaction_marker(
    *,
    transaction_marker: Path,
    library_existed: bool,
    wrapper_existed: bool,
) -> None:
    marker_staging = transaction_marker.with_name(f".{transaction_marker.name}.tmp")
    _remove_path(marker_staging)
    marker_staging.write_text(
        json.dumps(
            {
                "library_existed": library_existed,
                "wrapper_existed": wrapper_existed,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(marker_staging, transaction_marker)


def _publish_install(
    *,
    staging: Path,
    library_dir: Path,
    wrapper_staging: Path,
    plugin_entry: Path,
) -> None:
    library_backup = library_dir.with_name(".lib.backup")
    wrapper_backup = plugin_entry.with_name(".zara_discord.py.backup")
    transaction_marker = library_dir.parent / ".install-transaction.json"

    _recover_interrupted_publish(
        library_dir=library_dir,
        library_backup=library_backup,
        plugin_entry=plugin_entry,
        wrapper_backup=wrapper_backup,
        transaction_marker=transaction_marker,
    )

    library_existed = library_dir.exists()
    wrapper_existed = plugin_entry.exists()
    _write_transaction_marker(
        transaction_marker=transaction_marker,
        library_existed=library_existed,
        wrapper_existed=wrapper_existed,
    )

    try:
        if library_existed:
            os.replace(library_dir, library_backup)
        os.replace(staging, library_dir)

        if wrapper_existed:
            os.replace(plugin_entry, wrapper_backup)
        os.replace(wrapper_staging, plugin_entry)
    except BaseException:
        _restore_component(
            live=library_dir,
            backup=library_backup,
            existed=library_existed,
        )
        _restore_component(
            live=plugin_entry,
            backup=wrapper_backup,
            existed=wrapper_existed,
        )
        _remove_path(staging)
        _remove_path(wrapper_staging)
        _remove_path(library_backup)
        _remove_path(wrapper_backup)
        _remove_path(transaction_marker)
        raise

    # Marker deletion commits the new pair. Any backup surviving a process
    # death after this point is stale cleanup residue and must never be restored.
    _remove_path(transaction_marker)
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
