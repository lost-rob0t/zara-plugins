from __future__ import annotations

from typing import Any


class HomeError(RuntimeError):
    pass


class HomeService:
    def __init__(self, provider: Any) -> None:
        self.provider = provider

    def inventory(self) -> dict[str, Any]:
        devices = [self._normalize_device(device) for device in self.provider.list_devices()]
        devices.sort(key=lambda device: device["id"])
        rooms = sorted({device["room"] for device in devices if device.get("room")})
        return {"rooms": rooms, "devices": devices}

    def get_device(self, device_id: str) -> dict[str, Any]:
        device = self.provider.get_device(device_id)
        if device is None:
            raise HomeError(f"device not found: {device_id}")
        return self._normalize_device(device)

    def set_property(self, device_id: str, capability: str, value: Any) -> dict[str, Any]:
        before = self.get_device(device_id)
        spec = before["capabilities"].get(capability)
        if spec is None:
            raise HomeError(f"capability not found: {capability}")
        if spec.get("security_sensitive") is True:
            raise HomeError(f"security-sensitive capability requires an explicit privileged path: {capability}")
        self._validate_value(capability, spec, value)

        evidence = self.provider.set_property(device_id, capability, value)
        if not isinstance(evidence, dict):
            raise HomeError("provider returned invalid mutation evidence")
        after = self.get_device(device_id)
        observed = after["state"].get(capability)
        return {
            "device_id": device_id,
            "capability": capability,
            "requested": value,
            "observed": observed,
            "verified": observed == value,
            "provider_evidence": dict(evidence),
        }

    def activate_scene(self, scene_id: str) -> dict[str, Any]:
        if not isinstance(scene_id, str) or not scene_id.strip():
            raise HomeError("scene id is required")
        evidence = self.provider.activate_scene(scene_id)
        if not isinstance(evidence, dict):
            raise HomeError("provider returned invalid scene evidence")
        return {
            "scene_id": scene_id,
            "provider_evidence": dict(evidence),
            "verified": bool(evidence.get("verified", False)),
        }

    @staticmethod
    def _normalize_device(device: Any) -> dict[str, Any]:
        if not isinstance(device, dict):
            raise HomeError("provider returned an invalid device")
        device_id = device.get("id")
        if not isinstance(device_id, str) or not device_id:
            raise HomeError("provider device is missing an id")
        room = device.get("room")
        if room is not None and not isinstance(room, str):
            raise HomeError(f"device {device_id} has an invalid room")
        capabilities = device.get("capabilities", {})
        state = device.get("state", {})
        if not isinstance(capabilities, dict) or not isinstance(state, dict):
            raise HomeError(f"device {device_id} has invalid capability/state data")
        return {
            "id": device_id,
            "room": room,
            "capabilities": {name: dict(spec) for name, spec in capabilities.items()},
            "state": dict(state),
        }

    @staticmethod
    def _validate_value(capability: str, spec: dict[str, Any], value: Any) -> None:
        kind = spec.get("type")
        if kind == "enum":
            values = spec.get("values")
            if not isinstance(values, list) or value not in values:
                raise HomeError(f"value is not allowed for {capability}")
            return
        if kind == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise HomeError(f"numeric value required for {capability}")
            minimum = spec.get("minimum")
            maximum = spec.get("maximum")
            if minimum is not None and value < minimum:
                raise HomeError(f"value is outside allowed range for {capability}")
            if maximum is not None and value > maximum:
                raise HomeError(f"value is outside allowed range for {capability}")
            return
        if kind == "boolean":
            if not isinstance(value, bool):
                raise HomeError(f"boolean value required for {capability}")
            return
        raise HomeError(f"unsupported capability type for {capability}: {kind!r}")
