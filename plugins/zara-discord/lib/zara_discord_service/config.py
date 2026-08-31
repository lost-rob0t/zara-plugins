from __future__ import annotations

import json
import os
import stat
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


PLUGIN_NAME = "zara-discord"
SETTINGS_VERSION = 1


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class GuildPolicy:
    access_mode: str = "open"
    authorized_user_ids: frozenset[int] = frozenset()
    allowed_channel_ids: frozenset[int] = frozenset()


def config_directory() -> Path:
    xdg_root = os.environ.get("XDG_CONFIG_HOME")
    root = Path(xdg_root).expanduser() if xdg_root else Path.home() / ".config"
    return root / "zarathushtra" / "plugins" / PLUGIN_NAME


def load_token(directory: Path | None = None) -> str:
    environment_token = os.environ.get("ZARA_DISCORD_TOKEN", "").strip()
    if environment_token:
        return environment_token

    token_path = (directory or config_directory()) / "token"
    if not token_path.is_file():
        raise ConfigError(
            "Discord token not found; set ZARA_DISCORD_TOKEN or create "
            f"{token_path} with chmod 600"
        )
    if stat.S_IMODE(token_path.stat().st_mode) & 0o077:
        raise ConfigError(f"Discord token file is not private; run chmod 600 {token_path}")
    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise ConfigError(f"Discord token file is empty: {token_path}")
    return token


class PolicyStore:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or config_directory()
        self.path = self.directory / "settings.json"
        self._lock = threading.RLock()
        self._policies = self._load()

    def policy(self, guild_id: int) -> GuildPolicy:
        with self._lock:
            return self._policies.get(int(guild_id), GuildPolicy())

    def is_allowed(
        self,
        *,
        guild_id: int | None,
        user_id: int,
        channel_id: int,
        parent_channel_id: int | None = None,
    ) -> bool:
        if guild_id is None:
            with self._lock:
                restricted = tuple(
                    policy
                    for policy in self._policies.values()
                    if policy.access_mode == "restricted"
                )
            if not restricted:
                return True
            return any(
                int(user_id) in policy.authorized_user_ids
                for policy in restricted
            )
        policy = self.policy(guild_id)
        if (
            policy.access_mode == "restricted"
            and int(user_id) not in policy.authorized_user_ids
        ):
            return False
        if not policy.allowed_channel_ids:
            return True
        channel_ids = {int(channel_id)}
        if parent_channel_id is not None:
            channel_ids.add(int(parent_channel_id))
        return not policy.allowed_channel_ids.isdisjoint(channel_ids)

    def set_access_mode(self, guild_id: int, mode: str) -> None:
        if mode not in {"open", "restricted"}:
            raise ValueError("access mode must be open or restricted")
        self._update(guild_id, lambda policy: GuildPolicy(
            access_mode=mode,
            authorized_user_ids=policy.authorized_user_ids,
            allowed_channel_ids=policy.allowed_channel_ids,
        ))

    def add_authorized_user(self, guild_id: int, user_id: int) -> bool:
        return self._change_set(guild_id, "authorized_user_ids", user_id, add=True)

    def remove_authorized_user(self, guild_id: int, user_id: int) -> bool:
        return self._change_set(guild_id, "authorized_user_ids", user_id, add=False)

    def clear_authorized_users(self, guild_id: int) -> bool:
        return self._clear_set(guild_id, "authorized_user_ids")

    def add_allowed_channel(self, guild_id: int, channel_id: int) -> bool:
        return self._change_set(guild_id, "allowed_channel_ids", channel_id, add=True)

    def remove_allowed_channel(self, guild_id: int, channel_id: int) -> bool:
        return self._change_set(guild_id, "allowed_channel_ids", channel_id, add=False)

    def clear_allowed_channels(self, guild_id: int) -> bool:
        return self._clear_set(guild_id, "allowed_channel_ids")

    def _change_set(self, guild_id: int, field: str, value: int, *, add: bool) -> bool:
        changed = False

        def mutate(policy: GuildPolicy) -> GuildPolicy:
            nonlocal changed
            values = set(getattr(policy, field))
            before = set(values)
            values.add(int(value)) if add else values.discard(int(value))
            changed = values != before
            fields = {
                "access_mode": policy.access_mode,
                "authorized_user_ids": policy.authorized_user_ids,
                "allowed_channel_ids": policy.allowed_channel_ids,
            }
            fields[field] = frozenset(values)
            return GuildPolicy(**fields)

        self._update(guild_id, mutate, save_only_when=lambda: changed)
        return changed

    def _clear_set(self, guild_id: int, field: str) -> bool:
        changed = False

        def mutate(policy: GuildPolicy) -> GuildPolicy:
            nonlocal changed
            changed = bool(getattr(policy, field))
            fields = {
                "access_mode": policy.access_mode,
                "authorized_user_ids": policy.authorized_user_ids,
                "allowed_channel_ids": policy.allowed_channel_ids,
            }
            fields[field] = frozenset()
            return GuildPolicy(**fields)

        self._update(guild_id, mutate, save_only_when=lambda: changed)
        return changed

    def _update(
        self,
        guild_id: int,
        mutate: Callable[[GuildPolicy], GuildPolicy],
        save_only_when: Callable[[], bool] = lambda: True,
    ) -> None:
        guild_key = int(guild_id)
        with self._lock:
            self._policies[guild_key] = mutate(
                self._policies.get(guild_key, GuildPolicy())
            )
            if save_only_when():
                self._save()

    def _load(self) -> dict[int, GuildPolicy]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ConfigError(f"cannot read Discord plugin settings: {error}") from error
        if raw.get("version") != SETTINGS_VERSION:
            raise ConfigError(
                f"unsupported settings version {raw.get('version')!r}; "
                f"expected {SETTINGS_VERSION}"
            )
        guilds = raw.get("guilds", {})
        if not isinstance(guilds, dict):
            raise ConfigError("Discord plugin settings guilds must be an object")
        policies: dict[int, GuildPolicy] = {}
        try:
            for guild_id, value in guilds.items():
                mode = value.get("access_mode", "open")
                if mode not in {"open", "restricted"}:
                    raise ValueError(f"invalid access mode {mode!r}")
                policies[int(guild_id)] = GuildPolicy(
                    access_mode=mode,
                    authorized_user_ids=frozenset(
                        int(item) for item in value.get("authorized_user_ids", [])
                    ),
                    allowed_channel_ids=frozenset(
                        int(item) for item in value.get("allowed_channel_ids", [])
                    ),
                )
        except (AttributeError, TypeError, ValueError) as error:
            raise ConfigError(f"invalid Discord plugin settings: {error}") from error
        return policies

    def _save(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        serialized = {
            "version": SETTINGS_VERSION,
            "guilds": {
                str(guild_id): {
                    "access_mode": policy.access_mode,
                    "authorized_user_ids": sorted(policy.authorized_user_ids),
                    "allowed_channel_ids": sorted(policy.allowed_channel_ids),
                }
                for guild_id, policy in sorted(self._policies.items())
            },
        }
        temporary = self.directory / ".settings.json.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(serialized, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)
