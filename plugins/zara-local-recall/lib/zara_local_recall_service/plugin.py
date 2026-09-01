"""Zara service plugin wiring for the Local Recall integration."""

from __future__ import annotations

from . import cli
from .paths import PluginSettings

PLUGIN_NAME = "zara-local-recall"
PLUGIN_VERSION = "0.1.0"
PLUGIN_DESCRIPTION = (
    "Query Local Recall from Zara: cited activity answers, bounded search, "
    "daemon status, and policy-gated screen-context explanation."
)


class ZaraLocalRecallPlugin:
    def __init__(self) -> None:
        self._settings = PluginSettings()
        self._tools: list | None = None

    def start(self, runtime) -> None:
        self._settings = PluginSettings.from_configuration(dict(runtime.configuration))
        if not self._settings.enabled:
            return
        try:
            cli.status(settings=self._settings)
        except RuntimeError:
            pass

    def stop(self) -> None:
        self._tools = None

    def tools(self) -> list:
        if self._tools is None:
            from .tools import build_tools

            self._tools = build_tools(self._settings)
        return list(self._tools)


def create_plugin():
    from zara.plugins import PluginMetadata, ServicePlugin

    metadata = PluginMetadata(
        name=PLUGIN_NAME,
        version=PLUGIN_VERSION,
        api_version="1",
        description=PLUGIN_DESCRIPTION,
    )

    class ZaraLocalRecallService(ZaraLocalRecallPlugin, ServicePlugin):
        pass

    ZaraLocalRecallService.metadata = metadata
    return ZaraLocalRecallService()
