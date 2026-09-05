from __future__ import annotations

from typing import Any


class HomeAssistantError(RuntimeError):
    pass


class HomeAssistantAdapter:
    """Normalize a bounded Home Assistant REST seam into zara-home's domain model."""

    _DEVICE_DOMAINS = frozenset({"climate", "cover", "light", "lock", "switch"})

    def __init__(self, transport: Any) -> None:
        self.transport = transport

    def list_devices(self) -> list[dict[str, Any]]:
        states = self.transport.request("GET", "/api/states")
        if not isinstance(states, list):
            raise HomeAssistantError("Home Assistant states response must be a list")
        devices = []
        for state in states:
            if not isinstance(state, dict):
                continue
            entity_id = state.get("entity_id")
            if not isinstance(entity_id, str) or self._domain(entity_id) not in self._DEVICE_DOMAINS:
                continue
            devices.append(self._normalize(state))
        return devices

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        self._validate_entity_id(device_id)
        state = self.transport.request("GET", f"/api/states/{device_id}")
        if state is None:
            return None
        if not isinstance(state, dict):
            raise HomeAssistantError("Home Assistant device response must be an object")
        return self._normalize(state)

    def set_property(self, device_id: str, capability: str, value: Any) -> dict[str, Any]:
        domain = self._domain(device_id)
        if domain in {"light", "switch"} and capability == "power" and isinstance(value, bool):
            service = "turn_on" if value else "turn_off"
            payload = {"entity_id": device_id}
        elif domain == "climate" and capability == "temperature_c" and self._is_number(value):
            service = "set_temperature"
            payload = {"entity_id": device_id, "temperature": value}
        else:
            raise HomeAssistantError(f"unsupported Home Assistant mutation: {domain}.{capability}")

        response = self.transport.request("POST", f"/api/services/{domain}/{service}", payload)
        return {
            "provider": "home-assistant",
            "entity_id": device_id,
            "service": service,
            "response": response,
        }

    def activate_scene(self, scene_id: str) -> dict[str, Any]:
        if self._domain(scene_id) != "scene":
            raise HomeAssistantError("Home Assistant scene id must use the scene domain")
        response = self.transport.request(
            "POST",
            "/api/services/scene/turn_on",
            {"entity_id": scene_id},
        )
        return {
            "provider": "home-assistant",
            "entity_id": scene_id,
            "service": "turn_on",
            "response": response,
            "verified": False,
        }

    @classmethod
    def _normalize(cls, raw: dict[str, Any]) -> dict[str, Any]:
        entity_id = raw.get("entity_id")
        if not isinstance(entity_id, str):
            raise HomeAssistantError("Home Assistant entity is missing entity_id")
        domain = cls._domain(entity_id)
        attributes = raw.get("attributes") or {}
        if not isinstance(attributes, dict):
            raise HomeAssistantError(f"Home Assistant attributes are invalid for {entity_id}")
        room = attributes.get("area_name")
        if room is not None and not isinstance(room, str):
            room = None

        if domain in {"light", "switch"}:
            capabilities = {"power": {"type": "boolean"}}
            state = {"power": raw.get("state") == "on"}
        elif domain == "climate":
            spec: dict[str, Any] = {"type": "number"}
            minimum = attributes.get("min_temp")
            maximum = attributes.get("max_temp")
            if cls._is_number(minimum):
                spec["minimum"] = minimum
            if cls._is_number(maximum):
                spec["maximum"] = maximum
            capabilities = {"temperature_c": spec}
            state = {"temperature_c": attributes.get("temperature")}
        elif domain == "lock":
            capabilities = {"locked": {"type": "boolean", "security_sensitive": True}}
            state = {"locked": raw.get("state") == "locked"}
        elif domain == "cover":
            capabilities = {"open": {"type": "boolean", "security_sensitive": True}}
            state = {"open": raw.get("state") == "open"}
        else:
            raise HomeAssistantError(f"unsupported Home Assistant device domain: {domain}")

        return {
            "id": entity_id,
            "room": room,
            "capabilities": capabilities,
            "state": state,
        }

    @staticmethod
    def _domain(entity_id: str) -> str:
        if not isinstance(entity_id, str) or "." not in entity_id:
            raise HomeAssistantError("Home Assistant entity id must include a domain")
        domain, object_id = entity_id.split(".", 1)
        if not domain or not object_id:
            raise HomeAssistantError("Home Assistant entity id is invalid")
        return domain

    @classmethod
    def _validate_entity_id(cls, entity_id: str) -> None:
        domain = cls._domain(entity_id)
        if domain not in cls._DEVICE_DOMAINS:
            raise HomeAssistantError(f"unsupported Home Assistant device domain: {domain}")

    @staticmethod
    def _is_number(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
