from __future__ import annotations

import json
import os
import threading
from pathlib import Path


ACKNOWLEDGEMENT_ACTIONS = frozenset({"warn", "timeout", "kick", "ban"})
MAX_ACKNOWLEDGEMENT_LENGTH = 160
SETTINGS_VERSION = 1


class AcknowledgementConfigError(RuntimeError):
    pass


class ModerationAcknowledgementStore:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.path = self.directory / "moderation-acknowledgements.json"
        self._lock = threading.RLock()
        self._guilds, self._channels = self._load()

    def moderation_acknowledgement(
        self,
        guild_id: int,
        channel_id: int,
        action: str,
    ) -> str:
        action = self._validated_action(action)
        guild_key = self._validated_id(guild_id, "guild_id")
        channel_key = self._validated_id(channel_id, "channel_id")
        with self._lock:
            channel_value = self._channels.get((guild_key, channel_key, action))
            if channel_value is not None:
                return channel_value
            return self._guilds.get((guild_key, action), "")

    def set_moderation_acknowledgement(
        self,
        guild_id: int,
        action: str,
        text: str,
    ) -> None:
        guild_key = self._validated_id(guild_id, "guild_id")
        action = self._validated_action(action)
        value = self._validated_text(text)
        with self._lock:
            key = (guild_key, action)
            if value:
                self._guilds[key] = value
            else:
                self._guilds.pop(key, None)
            self._save()

    def set_channel_moderation_acknowledgement(
        self,
        guild_id: int,
        channel_id: int,
        action: str,
        text: str,
    ) -> None:
        guild_key = self._validated_id(guild_id, "guild_id")
        channel_key = self._validated_id(channel_id, "channel_id")
        action = self._validated_action(action)
        value = self._validated_text(text)
        with self._lock:
            key = (guild_key, channel_key, action)
            if value:
                self._channels[key] = value
            else:
                self._channels.pop(key, None)
            self._save()

    @staticmethod
    def _validated_action(action: str) -> str:
        value = str(action).strip().lower()
        if value not in ACKNOWLEDGEMENT_ACTIONS:
            raise ValueError("moderation action must be warn, timeout, kick, or ban")
        return value

    @staticmethod
    def _validated_id(value: int, field: str) -> int:
        result = int(value)
        if result < 0:
            raise ValueError(f"{field} must be non-negative")
        return result

    @staticmethod
    def _validated_text(text: str) -> str:
        value = str(text).strip()
        if not value:
            return ""
        if len(value) > MAX_ACKNOWLEDGEMENT_LENGTH:
            raise ValueError(
                f"moderation acknowledgement must be at most {MAX_ACKNOWLEDGEMENT_LENGTH} characters"
            )
        if any(character in value for character in ("\n", "\r", "\t")):
            raise ValueError("moderation acknowledgement must be single-line plain text")
        if any(ord(character) < 32 for character in value):
            raise ValueError("moderation acknowledgement must not contain control characters")
        if "@" in value:
            raise ValueError("moderation acknowledgement must not contain Discord mentions")
        return value

    def _load(
        self,
    ) -> tuple[dict[tuple[int, str], str], dict[tuple[int, int, str], str]]:
        if not self.path.exists():
            return {}, {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise AcknowledgementConfigError(
                f"cannot read Discord moderation acknowledgements: {error}"
            ) from error
        if raw.get("version") != SETTINGS_VERSION:
            raise AcknowledgementConfigError(
                f"unsupported moderation acknowledgement settings version {raw.get('version')!r}; "
                f"expected {SETTINGS_VERSION}"
            )
        guilds = raw.get("guilds", {})
        if not isinstance(guilds, dict):
            raise AcknowledgementConfigError("moderation acknowledgement guilds must be an object")
        guild_values: dict[tuple[int, str], str] = {}
        channel_values: dict[tuple[int, int, str], str] = {}
        try:
            for guild_id, guild_record in guilds.items():
                guild_key = self._validated_id(int(guild_id), "guild_id")
                if not isinstance(guild_record, dict):
                    raise ValueError("guild acknowledgement record must be an object")
                acknowledgements = guild_record.get("acknowledgements", {})
                if not isinstance(acknowledgements, dict):
                    raise ValueError("guild acknowledgements must be an object")
                for action, text in acknowledgements.items():
                    action_key = self._validated_action(action)
                    guild_values[(guild_key, action_key)] = self._validated_text(text)
                channels = guild_record.get("channels", {})
                if not isinstance(channels, dict):
                    raise ValueError("channel acknowledgements must be an object")
                for channel_id, channel_record in channels.items():
                    channel_key = self._validated_id(int(channel_id), "channel_id")
                    if not isinstance(channel_record, dict):
                        raise ValueError("channel acknowledgement record must be an object")
                    for action, text in channel_record.items():
                        action_key = self._validated_action(action)
                        channel_values[(guild_key, channel_key, action_key)] = self._validated_text(text)
        except (TypeError, ValueError) as error:
            raise AcknowledgementConfigError(
                f"invalid Discord moderation acknowledgement settings: {error}"
            ) from error
        return guild_values, channel_values

    def _save(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        guild_ids = {guild_id for guild_id, _action in self._guilds}
        guild_ids.update(guild_id for guild_id, _channel_id, _action in self._channels)
        serialized_guilds = {}
        for guild_id in sorted(guild_ids):
            acknowledgements = {
                action: text
                for (record_guild_id, action), text in sorted(self._guilds.items())
                if record_guild_id == guild_id
            }
            channel_ids = {
                channel_id
                for record_guild_id, channel_id, _action in self._channels
                if record_guild_id == guild_id
            }
            channels = {
                str(channel_id): {
                    action: text
                    for (record_guild_id, record_channel_id, action), text in sorted(
                        self._channels.items()
                    )
                    if record_guild_id == guild_id and record_channel_id == channel_id
                }
                for channel_id in sorted(channel_ids)
            }
            serialized_guilds[str(guild_id)] = {
                "acknowledgements": acknowledgements,
                "channels": channels,
            }
        serialized = {
            "version": SETTINGS_VERSION,
            "guilds": serialized_guilds,
        }
        temporary = self.directory / ".moderation-acknowledgements.json.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(serialized, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)
