import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_sysadmin.domain import SysadminExpert


class MalformedBooleanBackend:
    def service_status(self, unit):
        return {"active": "false", "result": "success", "substate": "running"}

    def service_action(self, unit, action):
        return {"accepted": "false"}

    def journal(self, unit, limit):
        return []

    def nix_generations(self, limit):
        return [{"generation": 7}]

    def nix_operation(self, operation, target):
        return {"accepted": "false"}


class AcceptedMalformedObservedBackend(MalformedBooleanBackend):
    def service_action(self, unit, action):
        return {"accepted": True}


class SysadminProviderBooleanTest(unittest.TestCase):
    def setUp(self):
        self.expert = SysadminExpert(MalformedBooleanBackend())

    def test_diagnostic_active_fact_rejects_truthy_non_boolean(self):
        result = self.expert.diagnose_service("demo.service")
        self.assertFalse(result["facts"]["service_active"])

    def test_service_action_rejects_malformed_acceptance_and_observed_state(self):
        result = self.expert.service_action("demo.service", "start")
        self.assertFalse(result["accepted"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["status"], "verification_failed")

    def test_service_action_requires_exact_boolean_observed_state(self):
        expert = SysadminExpert(AcceptedMalformedObservedBackend())
        for action in ("start", "stop"):
            with self.subTest(action=action):
                result = expert.service_action("demo.service", action)
                self.assertTrue(result["accepted"])
                self.assertFalse(result["verified"])
                self.assertEqual(result["status"], "verification_failed")

    def test_nix_operation_rejects_truthy_non_boolean_acceptance(self):
        result = self.expert.nix_operation("check", ".#demo")
        self.assertFalse(result["accepted"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["status"], "verification_failed")


if __name__ == "__main__":
    unittest.main()
