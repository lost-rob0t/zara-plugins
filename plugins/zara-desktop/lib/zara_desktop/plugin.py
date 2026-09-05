from __future__ import annotations

import json

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .desktop import DesktopConfig, DesktopService


PLUGIN_VERSION = "0.1.0"


class ZaraDesktopPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-desktop",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Structured Linux desktop control with bounded platform adapters",
    )

    def __init__(self) -> None:
        self._service = DesktopService()

    def start(self, runtime) -> None:
        self._service = DesktopService(DesktopConfig.load(runtime.configuration))

    def stop(self) -> None:
        return None

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def status(self) -> str:
        return self._json(self._service.status())

    def launch(self, application: str) -> str:
        return self._json(self._service.launch(application))

    def clipboard_read(self) -> str:
        return self._json(self._service.clipboard_read())

    def clipboard_write(self, text: str) -> str:
        return self._json(self._service.clipboard_write(text))

    def screenshot(self) -> str:
        return self._json(self._service.screenshot())

    def windows(self) -> str:
        return self._json(self._service.windows())

    def workspaces(self) -> str:
        return self._json(self._service.workspaces())

    def tools(self):
        operations = (
            (self.status, "desktop.status", "Report detected desktop capabilities without exposing private content."),
            (self.launch, "desktop.launch", "Launch one operator-configured application alias; arbitrary commands are not accepted."),
            (self.clipboard_read, "desktop.clipboard_read", "Read bounded clipboard content when a supported backend is available."),
            (self.clipboard_write, "desktop.clipboard_write", "Write bounded text to the clipboard when a supported backend is available."),
            (self.screenshot, "desktop.screenshot", "Capture a bounded PNG screenshot when a supported backend is available."),
            (self.windows, "desktop.windows", "List windows when a structured window backend is configured."),
            (self.workspaces, "desktop.workspaces", "List workspaces when a structured workspace backend is configured."),
        )
        return tuple(StructuredTool.from_function(func=func, name=name, description=description) for func, name, description in operations)


def create_plugin():
    return ZaraDesktopPlugin()
