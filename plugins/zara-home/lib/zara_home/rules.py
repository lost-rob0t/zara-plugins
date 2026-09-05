from __future__ import annotations

import re
from typing import Any


class RuleError(RuntimeError):
    pass


_COMFORT = re.compile(r"^make the ([a-z0-9_-]{1,64}) comfortable$", re.IGNORECASE)


class HomeRulePlanner:
    def __init__(self, home: Any) -> None:
        self.home = home

    def plan(self, intent: str) -> dict[str, Any]:
        if not isinstance(intent, str):
            raise RuleError("home intent must be text")
        match = _COMFORT.fullmatch(intent.strip())
        if match is None:
            raise RuleError("unsupported high-level home intent")
        room = match.group(1).lower()
        try:
            state = self.home.room_state(room)
        except Exception as exc:
            raise RuleError(f"room state is unavailable: {room}") from exc
        return self._comfort(room, state)

    @staticmethod
    def _comfort(room: str, state: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(state, dict):
            raise RuleError("room state must be structured data")
        presence = state.get("presence", {})
        environment = state.get("environment", {})
        devices = state.get("devices", [])
        if not isinstance(presence, dict) or not isinstance(environment, dict) or not isinstance(devices, list):
            raise RuleError("room state contains invalid structured data")

        occupied = presence.get("occupied") is True
        facts = [f"occupied({room})" if occupied else f"not_occupied({room})"]
        temperature = environment.get("temperature_c")
        if isinstance(temperature, (int, float)) and not isinstance(temperature, bool):
            facts.append(f"temperature_c({room},{temperature})")

        actions: list[dict[str, Any]] = []
        explanation: list[dict[str, str]] = []
        brightness_device = None
        thermostat = None
        for device in devices:
            if not isinstance(device, dict):
                continue
            capabilities = device.get("capabilities", {})
            observed = device.get("state", {})
            device_id = device.get("id")
            if not isinstance(device_id, str) or not isinstance(capabilities, dict) or not isinstance(observed, dict):
                continue
            if brightness_device is None and "brightness" in capabilities:
                brightness = observed.get("brightness")
                if isinstance(brightness, (int, float)) and not isinstance(brightness, bool):
                    facts.append(f"brightness({device_id},{brightness})")
                    brightness_device = device_id
            if thermostat is None and "target_temperature_c" in capabilities:
                thermostat = device_id

        if occupied and brightness_device is not None:
            actions.append({
                "device_id": brightness_device,
                "capability": "brightness",
                "value": 55,
                "rule": "comfort.occupied-light",
            })
            explanation.append({
                "rule": "comfort.occupied-light",
                "because": f"{room} is occupied and has a brightness-capable light",
            })

        if occupied and thermostat is not None and isinstance(temperature, (int, float)) and temperature < 20:
            actions.append({
                "device_id": thermostat,
                "capability": "target_temperature_c",
                "value": 21,
                "rule": "comfort.temperature-low",
            })
            explanation.append({
                "rule": "comfort.temperature-low",
                "because": f"observed {room} temperature {temperature}C is below the 20C comfort floor",
            })

        return {
            "intent": f"make the {room} comfortable",
            "room": room,
            "facts": facts,
            "actions": actions,
            "explanation": explanation,
            "mutated": False,
        }
