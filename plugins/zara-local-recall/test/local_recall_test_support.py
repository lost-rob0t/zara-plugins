"""Shared stand-ins for deterministic Local Recall plugin tests."""

from __future__ import annotations

import dataclasses
import sys
import types
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
LIB_ROOT = PLUGIN_ROOT / "lib"
for candidate in (str(LIB_ROOT), str(PLUGIN_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


@dataclasses.dataclass(frozen=True)
class PluginMetadata:
    name: str
    version: str = ""
    api_version: str = "1"
    plugin_type: str = "service"
    description: str = ""


class ServicePlugin:
    pass


def install_zara_stubs() -> None:
    if "zara" in sys.modules and hasattr(sys.modules["zara"], "plugins"):
        return
    module = types.ModuleType("zara")
    plugins = types.ModuleType("zara.plugins")
    plugins.PluginMetadata = PluginMetadata
    plugins.ServicePlugin = ServicePlugin
    module.plugins = plugins
    sys.modules["zara"] = module
    sys.modules["zara.plugins"] = plugins
