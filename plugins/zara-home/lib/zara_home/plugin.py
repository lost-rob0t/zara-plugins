from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .domain import HomeError, HomeService


PLUGIN_VERSION = "0.1.0"


class UnavailableHomeProvider:
    reason = "smart-home-provider-not-configured"

    def __getattr__(self, name):
        raise HomeError(self.reason)


class ZaraHomePlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-home",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Provider-neutral smart-home state and capability-safe control",
    )

    def __init__(self, provider=None) -> None:
        self.provider = provider or UnavailableHomeProvider()
        self.home = HomeService(self.provider)

    def start(self, runtime) -> None:
        return None

    def stop(self) -> None:
        return None

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

    def set_property(self, device_id: str, capability: str, value: Any) -> str:
        return self._json(self.home.set_property(device_id, capability, value))

    def activate_scene(self, scene_id: str) -> str:
        return self._json(self.home.activate_scene(scene_id))

    def tools(self):
        return (
            StructuredTool.from_function(func=self.status, name="home.status", description="Report whether a smart-home provider is configured."),
            StructuredTool.from_function(func=self.inventory, name="home.inventory", description="List normalized rooms, devices, capabilities and observed state."),
            StructuredTool.from_function(func=self.get_device, name="home.device.get", description="Read normalized state and capabilities for one device."),
            StructuredTool.from_function(func=self.set_property, name="home.device.set", description="Set one non-security-sensitive device capability after validating its allowed value/range and verify observed state."),
            StructuredTool.from_function(func=self.activate_scene, name="home.scene.activate", description="Activate one explicitly named scene and preserve provider evidence; provider verification is reported separately."),
        )


def create_plugin():
    return ZaraHomePlugin()
