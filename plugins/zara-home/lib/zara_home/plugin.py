from __future__ import annotations

import json
import os
from typing import Any

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .domain import HomeError, HomeService
from .home_assistant import HomeAssistantAdapter
from .home_assistant_events import HomeAssistantEventStream
from .home_assistant_transport import HomeAssistantHTTPError, HomeAssistantHTTPTransport
from .rules import HomeRulePlanner


PLUGIN_VERSION = "0.1.0"
_EVENT_JOIN_TIMEOUT_SECONDS = 15.0


class UnavailableHomeProvider:
    reason = "smart-home-provider-not-configured"

    def __init__(self, reason: str | None = None) -> None:
        if reason:
            self.reason = reason

    def __getattr__(self, name):
        raise HomeError(self.reason)


def _configured_components():
    base_url = os.environ.get("ZARA_HOME_ASSISTANT_URL")
    access_token = os.environ.get("ZARA_HOME_ASSISTANT_TOKEN")
    if base_url is None and access_token is None:
        return UnavailableHomeProvider(), None
    if not base_url or not access_token:
        return UnavailableHomeProvider("home-assistant-configuration-incomplete"), None
    try:
        transport = HomeAssistantHTTPTransport(base_url, access_token)
    except HomeAssistantHTTPError:
        return UnavailableHomeProvider("home-assistant-configuration-invalid"), None
    return HomeAssistantAdapter(transport), HomeAssistantEventStream.from_transport(transport)


def _configured_provider():
    provider, _ = _configured_components()
    return provider


class ZaraHomePlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-home",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Provider-neutral smart-home state and capability-safe control",
    )

    def __init__(self, provider=None, event_stream=None) -> None:
        if provider is None:
            provider, event_stream = _configured_components()
        self.provider = provider
        self.event_stream = event_stream
        self.home = HomeService(self.provider)
        self.planner = HomeRulePlanner(self.home)

    def start(self, runtime) -> None:
        if self.event_stream is not None:
            self.event_stream.start()

    def stop(self) -> None:
        if self.event_stream is None:
            return
        self.event_stream.stop()
        join = getattr(self.event_stream, "join", None)
        if callable(join):
            join(_EVENT_JOIN_TIMEOUT_SECONDS)
            return
        thread = getattr(self.event_stream, "_thread", None)
        if thread is not None:
            thread.join(timeout=_EVENT_JOIN_TIMEOUT_SECONDS)

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def status(self) -> str:
        if isinstance(self.provider, UnavailableHomeProvider):
            return self._json({"status": "unavailable", "reason": self.provider.reason})
        return self._json({"status": "ready"})

    def inventory(self) -> str:
        return self._json(self.home.inventory())

    def get_device(self, device_id: str) -> str:
        return self._json(self.home.get_device(device_id))

    def room_state(self, room: str) -> str:
        return self._json(self.home.room_state(room))

    def plan(self, intent: str) -> str:
        return self._json(self.planner.plan(intent))

    def set_property(self, device_id: str, capability: str, value: Any) -> str:
        return self._json(self.home.set_property(device_id, capability, value))

    def activate_scene(self, scene_id: str) -> str:
        return self._json(self.home.activate_scene(scene_id))

    def tools(self):
        return (
            StructuredTool.from_function(func=self.status, name="home.status", description="Report whether a smart-home provider is configured."),
            StructuredTool.from_function(func=self.inventory, name="home.inventory", description="List normalized rooms, devices, capabilities and observed state."),
            StructuredTool.from_function(func=self.get_device, name="home.device.get", description="Read normalized state and capabilities for one device."),
            StructuredTool.from_function(func=self.room_state, name="home.room.state", description="Read normalized device, presence, and environment state for one room."),
            StructuredTool.from_function(func=self.plan, name="home.plan", description="Translate a supported high-level home intent into an explained non-mutating fact-driven action plan."),
            StructuredTool.from_function(func=self.set_property, name="home.device.set", description="Set one non-security-sensitive device capability after validating its allowed value/range and verify observed state."),
            StructuredTool.from_function(func=self.activate_scene, name="home.scene.activate", description="Activate one explicitly named scene and preserve provider evidence; provider verification is reported separately."),
        )


def create_plugin():
    return ZaraHomePlugin()
