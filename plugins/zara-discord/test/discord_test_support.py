"""Small Zara API stand-ins for deterministic plugin tests."""

from __future__ import annotations

import dataclasses
import sys
import types
import uuid
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
LIB_ROOT = PLUGIN_ROOT / "lib"
if str(LIB_ROOT) not in sys.path:
    sys.path.insert(0, str(LIB_ROOT))


@dataclasses.dataclass(frozen=True)
class PluginMetadata:
    name: str
    version: str = ""
    api_version: str = "1"
    plugin_type: str = "service"
    description: str = ""


class ServicePlugin:
    pass


@dataclasses.dataclass(frozen=True, kw_only=True)
class RuntimeEvent:
    turn_id: str | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class ResponseText(RuntimeEvent):
    conversation_id: str | None = None
    text: str = ""


@dataclasses.dataclass(frozen=True, kw_only=True)
class AgentFailed(RuntimeEvent):
    reason: str = ""


@dataclasses.dataclass(frozen=True, kw_only=True)
class AssistantFailed(RuntimeEvent):
    reason: str = ""


@dataclasses.dataclass(frozen=True, kw_only=True)
class TurnCancelled(RuntimeEvent):
    reason: str = ""


@dataclasses.dataclass(frozen=True, kw_only=True)
class RuntimeIdle(RuntimeEvent):
    pass


@dataclasses.dataclass(frozen=True)
class SubmitTurn:
    text: str
    conversation_id: str
    request_id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))


@dataclasses.dataclass(frozen=True)
class CommandReceipt:
    request_id: str
    turn_id: str | None = None


def install_zara_stubs() -> None:
    zara_module = types.ModuleType("zara")
    plugins_module = types.ModuleType("zara.plugins")
    runtime_module = types.ModuleType("zara.runtime")
    events_module = types.ModuleType("zara.runtime.events")
    commands_module = types.ModuleType("zara.runtime.commands")

    plugins_module.PluginMetadata = PluginMetadata
    plugins_module.ServicePlugin = ServicePlugin
    events_module.ResponseText = ResponseText
    events_module.AgentFailed = AgentFailed
    events_module.AssistantFailed = AssistantFailed
    events_module.TurnCancelled = TurnCancelled
    events_module.RuntimeIdle = RuntimeIdle
    commands_module.SubmitTurn = SubmitTurn
    commands_module.CommandReceipt = CommandReceipt
    runtime_module.events = events_module
    runtime_module.commands = commands_module
    zara_module.plugins = plugins_module
    zara_module.runtime = runtime_module

    sys.modules["zara"] = zara_module
    sys.modules["zara.plugins"] = plugins_module
    sys.modules["zara.runtime"] = runtime_module
    sys.modules["zara.runtime.events"] = events_module
    sys.modules["zara.runtime.commands"] = commands_module
