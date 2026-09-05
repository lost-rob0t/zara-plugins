import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_home.home_assistant import HomeAssistantAdapter, HomeAssistantError


class FakeTransport:
    def __init__(self):
        self.states = {
            "light.office": {"entity_id": "light.office", "state": "off", "attributes": {"friendly_name": "Office", "area_name": "office", "brightness": 0}},
            "climate.office": {"entity_id": "climate.office", "state": "heat", "attributes": {"area_name": "office", "temperature": 19.0, "min_temp": 7.0, "max_temp": 35.0}},
            "lock.front": {"entity_id": "lock.front", "state": "locked", "attributes": {"area_name": "entry"}},
        }
        self.calls = []

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == "GET" and path == "/api/states":
            return list(self.states.values())
        if method == "GET" and path.startswith("/api/states/"):
            return self.states.get(path.removeprefix("/api/states/"))
        if method == "POST" and path == "/api/services/light/turn_on":
            entity_id = payload["entity_id"]
            self.states[entity_id]["state"] = "on"
            return [{"entity_id": entity_id}]
        if method == "POST" and path == "/api/services/light/turn_off":
            entity_id = payload["entity_id"]
            self.states[entity_id]["state"] = "off"
            return [{"entity_id": entity_id}]
        if method == "POST" and path == "/api/services/climate/set_temperature":
            entity_id = payload["entity_id"]
            self.states[entity_id]["attributes"]["temperature"] = payload["temperature"]
            return [{"entity_id": entity_id}]
        raise AssertionError((method, path, payload))


class HomeAssistantAdapterTests(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.adapter = HomeAssistantAdapter(self.transport)

    def test_normalizes_provider_state_without_leaking_wire_schema(self):
        devices = {device["id"]: device for device in self.adapter.list_devices()}
        light = devices["light.office"]
        self.assertEqual(light["room"], "office")
        self.assertEqual(light["state"]["power"], False)
        self.assertEqual(light["capabilities"]["power"], {"type": "boolean"})
        climate = devices["climate.office"]
        self.assertEqual(climate["state"]["temperature_c"], 19.0)
        self.assertEqual(climate["capabilities"]["temperature_c"]["minimum"], 7.0)
        self.assertTrue(devices["lock.front"]["capabilities"]["locked"]["security_sensitive"])

    def test_maps_bounded_properties_to_explicit_services(self):
        evidence = self.adapter.set_property("light.office", "power", True)
        self.assertEqual(self.transport.calls[-1][1], "/api/services/light/turn_on")
        self.assertEqual(evidence["provider"], "home-assistant")
        self.assertEqual(self.adapter.get_device("light.office")["state"]["power"], True)

        self.adapter.set_property("climate.office", "temperature_c", 21.5)
        self.assertEqual(self.transport.calls[-1][2]["temperature"], 21.5)

    def test_rejects_unsupported_domain_or_capability(self):
        with self.assertRaises(HomeAssistantError):
            self.adapter.set_property("lock.front", "locked", False)
        with self.assertRaises(HomeAssistantError):
            self.adapter.set_property("light.office", "brightness", 50)


if __name__ == "__main__":
    unittest.main()
