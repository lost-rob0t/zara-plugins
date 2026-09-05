import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_home.domain import HomeError, HomeService


class FakeProvider:
    def __init__(self):
        self.devices = {
            "office-light": {
                "id": "office-light",
                "room": "office",
                "capabilities": {
                    "power": {"type": "enum", "values": ["on", "off"]},
                    "brightness": {"type": "number", "minimum": 0, "maximum": 100},
                },
                "state": {"power": "off", "brightness": 20},
            },
            "front-lock": {
                "id": "front-lock",
                "room": "entry",
                "capabilities": {"lock": {"type": "enum", "values": ["locked", "unlocked"], "security_sensitive": True}},
                "state": {"lock": "locked"},
            },
        }
        self.actions = []

    def list_devices(self):
        return list(self.devices.values())

    def get_device(self, device_id):
        return self.devices.get(device_id)

    def set_property(self, device_id, capability, value):
        self.actions.append((device_id, capability, value))
        self.devices[device_id]["state"][capability] = value
        return {"provider_request_id": "req-1", "accepted": True}

    def activate_scene(self, scene_id):
        return {"scene_id": scene_id, "accepted": True, "provider_request_id": "scene-1"}


class HomeServiceTests(unittest.TestCase):
    def setUp(self):
        self.provider = FakeProvider()
        self.home = HomeService(self.provider)

    def test_normalizes_room_and_device_inventory(self):
        result = self.home.inventory()
        self.assertEqual(result["rooms"], ["entry", "office"])
        self.assertEqual(result["devices"][0]["id"], "front-lock")

    def test_validates_numeric_range_before_provider_write(self):
        with self.assertRaisesRegex(HomeError, "range"):
            self.home.set_property("office-light", "brightness", 101)
        self.assertEqual(self.provider.actions, [])

    def test_validates_enum_before_provider_write(self):
        with self.assertRaisesRegex(HomeError, "allowed"):
            self.home.set_property("office-light", "power", "blink")
        self.assertEqual(self.provider.actions, [])

    def test_vague_intent_cannot_mutate_security_sensitive_capability(self):
        with self.assertRaisesRegex(HomeError, "security-sensitive"):
            self.home.set_property("front-lock", "lock", "unlocked")
        self.assertEqual(self.provider.actions, [])

    def test_mutation_is_verified_against_observed_state(self):
        result = self.home.set_property("office-light", "brightness", 55)
        self.assertTrue(result["verified"])
        self.assertEqual(result["observed"], 55)
        self.assertEqual(result["provider_evidence"]["provider_request_id"], "req-1")

    def test_provider_acceptance_without_observed_change_is_not_success(self):
        class LyingProvider(FakeProvider):
            def set_property(self, device_id, capability, value):
                self.actions.append((device_id, capability, value))
                return {"provider_request_id": "req-lie", "accepted": True}

        home = HomeService(LyingProvider())
        result = home.set_property("office-light", "power", "on")
        self.assertFalse(result["verified"])
        self.assertEqual(result["observed"], "off")

    def test_missing_provider_data_fails_honestly(self):
        with self.assertRaisesRegex(HomeError, "not found"):
            self.home.get_device("missing")


if __name__ == "__main__":
    unittest.main()
