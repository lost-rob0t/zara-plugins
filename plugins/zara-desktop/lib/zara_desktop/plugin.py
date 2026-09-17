from __future__ import annotations

import json

from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .desktop import DesktopConfig, DesktopService


PLUGIN_VERSION = "0.2.0"


class ZaraDesktopPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-desktop",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Structured Linux desktop control with bounded platform adapters",
    )

    def __init__(self) -> None:
        self._service = DesktopService()
        self._screenshot_hook_registration_id = None

    def start(self, runtime) -> None:
        config = DesktopConfig.load(runtime.configuration)
        self._service = DesktopService(config)
        self._screenshot_hook_registration_id = None
        if config.screenshot_context_hook_enabled:
            self._screenshot_hook_registration_id = runtime.register_agent_loop_advice(
                "before",
                config.screenshot_context_hook_priority,
                self._inject_screenshot_context,
            )

    def stop(self) -> None:
        return None

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def _inject_screenshot_context(self, _llm_client, _tool_registry, state, **_kwargs) -> None:
        result = self._service.screenshot()
        if result.get("status") != "ok":
            return
        mime_type = result.get("mime_type")
        encoded = result.get("data_base64")
        if mime_type != "image/png" or not isinstance(encoded, str) or not encoded:
            return
        messages = state.get("messages")
        if not isinstance(messages, list) or not messages:
            return
        message = messages[-1]
        if not isinstance(message, HumanMessage):
            return
        content = message.content
        if isinstance(content, str):
            multimodal = [{"type": "text", "text": content}]
        elif isinstance(content, list):
            multimodal = list(content)
        else:
            return
        multimodal.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{encoded}"},
            }
        )
        model_copy = getattr(message, "model_copy", None)
        if callable(model_copy):
            messages[-1] = model_copy(update={"content": multimodal})
        else:
            messages[-1] = HumanMessage(
                content=multimodal,
                id=getattr(message, "id", None),
            )

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
            (self.screenshot, "desktop.screenshot", "Capture a bounded PNG screenshot with grim or scrot when a supported backend is available."),
            (self.windows, "desktop.windows", "List windows when a structured window backend is configured."),
            (self.workspaces, "desktop.workspaces", "List workspaces when a structured workspace backend is configured."),
        )
        return tuple(StructuredTool.from_function(func=func, name=name, description=description) for func, name, description in operations)


def create_plugin():
    return ZaraDesktopPlugin()
