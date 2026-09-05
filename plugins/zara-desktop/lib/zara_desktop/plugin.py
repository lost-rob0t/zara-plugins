"""Zara service plugin for structured desktop operations."""

from __future__ import annotations

import json

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .config import DesktopConfig
from .core import DesktopController
from .linux import LinuxBackend


PLUGIN_VERSION = "0.1.0"


class ZaraDesktopPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-desktop",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Structured desktop control and capability-aware context primitives",
    )

    def __init__(self) -> None:
        self._controller = DesktopController(LinuxBackend())

    def start(self, runtime) -> None:
        config = DesktopConfig.load(runtime.configuration)
        self._controller = DesktopController(
            LinuxBackend(),
            applications=config.applications,
            max_text_bytes=config.max_text_bytes,
            max_events=config.max_events,
        )

    def stop(self) -> None:
        return None

    def tools(self):
        specs = (
            (self.status, "desktop.status", "Report the active desktop backend and explicit capability support."),
            (self.launch, "desktop.launch", "Launch one user-configured application alias with fixed argv."),
            (self.windows, "desktop.windows", "List structured observed desktop windows when supported."),
            (self.focus_window, "desktop.window.focus", "Focus an observed window by backend identifier."),
            (self.close_window, "desktop.window.close", "Close an observed window by backend identifier."),
            (self.workspaces, "desktop.workspaces", "List structured observed workspaces when supported."),
            (self.switch_workspace, "desktop.workspace.switch", "Switch to an observed workspace identifier."),
            (self.clipboard_get, "desktop.clipboard.get", "Read bounded text clipboard content when supported."),
            (self.clipboard_set, "desktop.clipboard.set", "Write bounded text clipboard content when supported."),
            (self.screenshot, "desktop.screenshot", "Capture a bounded screenshot into user-writable runtime state when supported."),
            (self.events, "desktop.events", "Read bounded structured desktop events from the backend event interface."),
        )
        return tuple(
            StructuredTool.from_function(func=func, name=name, description=description)
            for func, name, description in specs
        )

    @staticmethod
    def _json(value) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def status(self) -> str:
        return self._json(self._controller.status())

    def launch(self, application_id: str) -> str:
        return self._json(self._controller.launch(application_id))

    def windows(self) -> str:
        return self._json(self._controller.windows())

    def focus_window(self, window_id: str) -> str:
        return self._json(self._controller.focus_window(window_id))

    def close_window(self, window_id: str) -> str:
        return self._json(self._controller.close_window(window_id))

    def workspaces(self) -> str:
        return self._json(self._controller.workspaces())

    def switch_workspace(self, workspace_id: str) -> str:
        return self._json(self._controller.switch_workspace(workspace_id))

    def clipboard_get(self) -> str:
        return self._json(self._controller.clipboard_get())

    def clipboard_set(self, text: str) -> str:
        return self._json(self._controller.clipboard_set(text))

    def screenshot(self) -> str:
        return self._json(self._controller.screenshot())

    def events(self, limit: int = 20) -> str:
        return self._json(self._controller.events(limit=limit))


def create_plugin():
    return ZaraDesktopPlugin()
