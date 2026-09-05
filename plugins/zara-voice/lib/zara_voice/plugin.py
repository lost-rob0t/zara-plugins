from __future__ import annotations

import json

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .domain import VoiceDomain, VoiceError


PLUGIN_VERSION = "0.1.0"


class ZaraVoicePlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-voice",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Provider-neutral bounded runtime speech synthesis and playback",
    )

    def __init__(self, backends=None) -> None:
        self.backends = dict(backends or {})
        self.domain = None
        self._configuration = {}

    def start(self, runtime) -> None:
        configuration = runtime.configuration if isinstance(runtime.configuration, dict) else {}
        plugins = configuration.get("plugins", {}) if isinstance(configuration, dict) else {}
        section = plugins.get("zara-voice", {}) if isinstance(plugins, dict) else {}
        self._configuration = section if isinstance(section, dict) else {}
        self._build_domain()

    def stop(self) -> None:
        self.domain = None

    def _build_domain(self) -> None:
        if not self.backends:
            self.domain = None
            return
        self.domain = VoiceDomain(
            self.backends,
            allow_remote=bool(self._configuration.get("allow_remote", False)),
            max_text_bytes=int(self._configuration.get("max_text_bytes", 8192)),
            max_duration_ms=int(self._configuration.get("max_duration_ms", 300000)),
        )

    def _domain(self) -> VoiceDomain:
        if self.domain is None:
            raise VoiceError("voice-backend-not-configured")
        return self.domain

    @staticmethod
    def _json(value) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def status(self) -> str:
        if self.domain is None:
            return self._json({"status": "unavailable", "reason": "voice-backend-not-configured"})
        return self._json({"status": "ready", "backends": self.domain.backends()})

    def list_backends(self) -> str:
        return self._json(self._domain().backends())

    def list_profiles(self, backend: str) -> str:
        return self._json(self._domain().profiles(backend))

    def synthesize(
        self,
        text: str,
        backend: str,
        profile_id: str,
        language: str = "",
        style: str = "",
        emotion: str = "",
    ) -> str:
        return self._json(
            self._domain().synthesize(
                text,
                backend=backend,
                profile_id=profile_id,
                language=language or None,
                style=style or None,
                emotion=emotion or None,
            )
        )

    def play(self, artifact_id: str, backend: str) -> str:
        return self._json(self._domain().play(artifact_id, backend=backend))

    def cancel(self, playback_id: str, backend: str) -> str:
        return self._json(self._domain().cancel(playback_id, backend=backend))

    def tools(self):
        return (
            StructuredTool.from_function(
                func=self.status,
                name="voice.status",
                description="Report configured runtime voice backend availability without exposing credentials.",
            ),
            StructuredTool.from_function(
                func=self.list_backends,
                name="voice.backends",
                description="List normalized voice backend capabilities and locality.",
            ),
            StructuredTool.from_function(
                func=self.list_profiles,
                name="voice.profiles",
                description="List bounded voice profiles for one configured backend.",
            ),
            StructuredTool.from_function(
                func=self.synthesize,
                name="voice.synthesize",
                description="Synthesize bounded text with an explicit backend/profile and capability-gated language/style/emotion.",
            ),
            StructuredTool.from_function(
                func=self.play,
                name="voice.play",
                description="Play a synthesized artifact and verify observed playback state.",
            ),
            StructuredTool.from_function(
                func=self.cancel,
                name="voice.cancel",
                description="Cancel a playback by stable id and verify the observed stopped/cancelled state.",
            ),
        )


def create_plugin():
    return ZaraVoicePlugin()
