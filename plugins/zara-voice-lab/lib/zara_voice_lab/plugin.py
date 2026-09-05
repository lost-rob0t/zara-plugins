from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .domain import VoiceLabError, VoiceLabPolicy, VoiceLabService


PLUGIN_VERSION = "0.1.0"


class ZaraVoiceLabPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-voice-lab",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Bounded provenance-first voice creation and preview workbench",
    )

    def __init__(
        self,
        *,
        backends: dict[str, Any] | None = None,
        workspace_root: Path | None = None,
        policy: VoiceLabPolicy | None = None,
    ) -> None:
        data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        self.backends = dict(backends or {})
        self.lab = VoiceLabService(
            backends=self.backends,
            workspace_root=workspace_root or data_home / "zarathushtra" / "zara-voice-lab",
            policy=policy,
        )

    def start(self, runtime) -> None:
        return None

    def stop(self) -> None:
        return None

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def status(self) -> str:
        if not self.backends:
            return self._json({"status": "unavailable", "reason": "voice-lab-backend-not-configured"})
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

    def preview(self, profile_id: str, text: str, style: str | None = None) -> str:
        return self._json(self.lab.preview(profile_id, text, style=style))

    def export_profile(self, profile_id: str) -> str:
        return self._json(self.lab.export_profile(profile_id))

    def tools(self):
        return (
            StructuredTool.from_function(func=self.status, name="voice_lab.status", description="Report configured voice-workbench backends, locality, and capabilities."),
            StructuredTool.from_function(func=self.preview, name="voice_lab.preview", description="Generate bounded preview metadata for a known workbench profile without returning raw audio."),
            StructuredTool.from_function(func=self.export_profile, name="voice_lab.export", description="Export stable runtime profile metadata consumable by zara-voice; source audio and model weights are excluded."),
        )


def create_plugin():
    return ZaraVoiceLabPlugin()
