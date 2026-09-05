import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_home.rules import HomeRulePlanner, RuleError


class FakeHome:
    def room_state(self, room):
        if room == "office":
            return {
                "room": "office",
                "presence": {"occupied": True},
                "environment": {"temperature_c": 18.0},
                "devices": [
                    {
                        "id": "office-light",
                        "capabilities": {"brightness": {"type": "number", "minimum": 0, "maximum": 100}},
                        "state": {"brightness": 20},
                    },
                    {
                        "id": "office-thermostat",
                        "capabilities": {"target_temperature_c": {"type": "number", "minimum": 16, "maximum": 28}},
                        "state": {"target_temperature_c": 18},
                    },
                ],
            }
        if room == "empty":
            return {"room": "empty", "presence": {"occupied": False}, "environment": {}, "devices": []}
        raise KeyError(room)


class HomeRulePlannerTests(unittest.TestCase):
    def setUp(self):
        self.planner = HomeRulePlanner(FakeHome())

    def test_comfort_plan_is_fact_driven_and_non_mutating(self):
        plan = self.planner.plan("make the office comfortable")
        self.assertEqual(plan["room"], "office")
        self.assertEqual(
            plan["facts"],
            ["occupied(office)", "temperature_c(office,18.0)", "brightness(office-light,20)"],
        )
        self.assertEqual(
            plan["actions"],
            [
                {"device_id": "office-light", "capability": "brightness", "value": 55, "rule": "comfort.occupied-light"},
                {"device_id": "office-thermostat", "capability": "target_temperature_c", "value": 21, "rule": "comfort.temperature-low"},
            ],
        )

    def test_empty_room_produces_no_comfort_mutations(self):
        plan = self.planner.plan("make the empty comfortable")
        self.assertEqual(plan["actions"], [])
        self.assertIn("not_occupied(empty)", plan["facts"])

    def test_unknown_intent_fails_instead_of_guessing(self):
        with self.assertRaisesRegex(RuleError, "unsupported"):
            self.planner.plan("do something cool")

    def test_plan_contains_explanation_for_every_action(self):
        plan = self.planner.plan("make the office comfortable")
        self.assertEqual(
            [entry["rule"] for entry in plan["explanation"]],
            ["comfort.occupied-light", "comfort.temperature-low"],
        )
        self.assertTrue(all(entry["because"] for entry in plan["explanation"]))


if __name__ == "__main__":
    unittest.main()
