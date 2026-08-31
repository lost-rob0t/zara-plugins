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
    if staging.exists():
        shutil.rmtree(staging)
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

    if library_dir.exists():
        shutil.rmtree(library_dir)
    staging.replace(library_dir)

    wrapper_source = plugin_root / "zara-plugin" / "zara_discord.py"
    shutil.copy2(wrapper_source, plugin_entry)
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
