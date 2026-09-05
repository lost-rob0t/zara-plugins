from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .domain import VoiceError, VoicePolicy, VoiceProfile, VoiceService


PLUGIN_VERSION = "0.1.0"


class UnavailablePlayer:
    reason = "audio-player-not-configured"

    def play(self, artifact):
        raise VoiceError(self.reason)

    def cancel(self, playback_id):
        return False


class ZaraVoicePlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-voice",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Bounded provider-neutral runtime TTS and voice profiles",
    )

    def __init__(
        self,
        *,
        backends: dict[str, Any] | None = None,
        player: Any | None = None,
        profiles: tuple[VoiceProfile, ...] = (),
        cache_root: Path | None = None,
        policy: VoicePolicy | None = None,
    ) -> None:
        cache_home = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        self.backends = dict(backends or {})
        self.player = player or UnavailablePlayer()
        self.voice = VoiceService(
            backends=self.backends,
            player=self.player,
            cache_root=cache_root or cache_home / "zarathushtra" / "zara-voice",
            policy=policy,
        )
        for profile in profiles:
            self.voice.register_profile(profile)

    def start(self, runtime) -> None:
        return None

    def stop(self) -> None:
        return None

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def status(self) -> str:
        if not self.backends:
            return self._json({"status": "unavailable", "reason": "tts-backend-not-configured"})
        return self._json(
            {
                "status": "ready",
                "backends": [
                    {
                        "name": name,
                        "locality": str(getattr(backend, "locality", "unknown")),
                        "capabilities": sorted(str(item) for item in getattr(backend, "capabilities", ())),
                    }
                    for name, backend in sorted(self.backends.items())
                ],
            }
        )

    def profiles(self) -> str:
        return self._json(self.voice.profiles())

    def synthesize(
        self,
        text: str,
        profile: str,
        language: str | None = None,
        style: str | None = None,
        emotion: str | None = None,
        cache: bool = True,
    ) -> str:
        return self._json(
            self.voice.synthesize(
                text,
                profile=profile,
                language=language,
                style=style,
                emotion=emotion,
                cache=cache,
            )
        )

    def play(self, artifact_id: str) -> str:
        return self._json(self.voice.play(artifact_id))

    def cancel(self, playback_id: str | None = None, request_id: str | None = None) -> str:
        return self._json(self.voice.cancel(playback_id=playback_id, request_id=request_id))

    def tools(self):
        return (
            StructuredTool.from_function(func=self.status, name="voice.status", description="Report configured runtime TTS backends, locality and capabilities."),
            StructuredTool.from_function(func=self.profiles, name="voice.profiles", description="List selectable runtime voice profiles and backend metadata."),
            StructuredTool.from_function(func=self.synthesize, name="voice.synthesize", description="Synthesize bounded text with an explicitly selected voice profile; remote backends require host policy opt-in."),
            StructuredTool.from_function(func=self.play, name="voice.play", description="Play a previously synthesized in-memory audio artifact by ID."),
            StructuredTool.from_function(func=self.cancel, name="voice.cancel", description="Cancel exactly one active playback or backend synthesis request by ID."),
        )


def create_plugin():
    return ZaraVoicePlugin()
