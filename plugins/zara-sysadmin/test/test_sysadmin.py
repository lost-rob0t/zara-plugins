import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_sysadmin.domain import SysadminError, SysadminExpert


class FakeSystemBackend:
    def __init__(self):
        self.services = {
            "demo.service": {"active": False, "result": "exit-code", "substate": "failed"},
            "web.service": {"active": True, "result": "success", "substate": "running"},
        }
        self.journals = {"demo.service": ["failed to open config", "exit status 1"]}
        self.listeners = {8080: False}
        self.interfaces = {"eth0": {"up": True, "addresses": ["192.0.2.2/24"]}}
        self.routes = [{"destination": "default", "gateway": "192.0.2.1"}]
        self.dns = {"resolver_configured": True, "upstream_reachable": False}
        self.generation = 42
        self.verify_restart = True

    def service_status(self, unit):
        return dict(self.services.get(unit, {"active": False, "result": "not-found", "substate": "dead"}))

    def service_action(self, unit, action):
        before = self.service_status(unit)
        if action == "restart" and unit in self.services and self.verify_restart:
            self.services[unit] = {"active": True, "result": "success", "substate": "running"}
        return {"accepted": True, "unit": unit, "action": action, "before": before}

    def journal(self, unit, limit):
        return list(self.journals.get(unit, []))[-limit:]

    def listener(self, port):
        return {"port": port, "listening": bool(self.listeners.get(port, False))}

    def process_summary(self, limit):
        return [{"pid": 1, "name": "init", "cpu_percent": 0.0, "memory_bytes": 1024}][:limit]

    def resource_summary(self):
        return {"load": [0.1, 0.2, 0.3], "memory": {"used": 100, "total": 1000}, "filesystems": []}

    def network_summary(self):
        return {"interfaces": self.interfaces, "routes": self.routes, "dns": self.dns}

    def nix_generations(self, limit):
        return [{"generation": self.generation, "current": True}][:limit]

    def nix_operation(self, operation, target):
        before = self.generation
        if operation == "switch":
            self.generation += 1
        return {"accepted": True, "operation": operation, "target": target, "before_generation": before}


class SysadminExpertTest(unittest.TestCase):
    def setUp(self):
        self.backend = FakeSystemBackend()
        self.expert = SysadminExpert(self.backend, max_log_lines=32, max_processes=16)

    def test_failed_service_preserves_unit_and_recent_journal_evidence(self):
        result = self.expert.diagnose_service("demo.service")
        self.assertEqual(result["status"], "diagnosed")
        self.assertEqual(result["facts"]["service_result"], "exit-code")
        self.assertEqual(result["evidence"]["journal"], ["failed to open config", "exit status 1"])
        self.assertIn("service_failed", result["hypotheses"])
        self.assertIn("inspect_recent_journal", result["next_diagnostics"])

    def test_running_service_with_closed_port_derives_listener_path(self):
        result = self.expert.diagnose_service_port("web.service", 8080)
        self.assertTrue(result["facts"]["service_active"])
        self.assertFalse(result["facts"]["port_listening"])
        self.assertIn("running_without_listener", result["hypotheses"])
        self.assertIn("inspect_socket_or_service_config", result["next_diagnostics"])

    def test_dns_diagnosis_distinguishes_resolver_route_and_upstream(self):
        result = self.expert.diagnose_dns()
        self.assertTrue(result["facts"]["resolver_configured"])
        self.assertTrue(result["facts"]["default_route_present"])
        self.assertFalse(result["facts"]["dns_upstream_reachable"])
        self.assertIn("dns_upstream_failure", result["hypotheses"])

    def test_restart_never_claims_success_without_post_change_verification(self):
        success = self.expert.service_action("demo.service", "restart")
        self.assertTrue(success["accepted"])
        self.assertTrue(success["verified"])
        self.assertTrue(success["after"]["active"])

        self.backend.services["demo.service"] = {"active": False, "result": "exit-code", "substate": "failed"}
        self.backend.verify_restart = False
        failed = self.expert.service_action("demo.service", "restart")
        self.assertTrue(failed["accepted"])
        self.assertFalse(failed["verified"])
        self.assertEqual(failed["status"], "verification_failed")

    def test_mutation_action_and_log_limits_are_allowlisted_and_bounded(self):
        with self.assertRaises(SysadminError):
            self.expert.service_action("demo.service", "enable --now")
        with self.assertRaises(SysadminError):
            self.expert.journal("demo.service", 1000)
        self.assertLessEqual(len(self.expert.journal("demo.service", 2)["lines"]), 2)

    def test_nix_switch_preserves_generation_evidence_and_verifies_change(self):
        result = self.expert.nix_operation("switch", ".#host")
        self.assertEqual(result["before_generation"], 42)
        self.assertEqual(result["after_generation"], 43)
        self.assertTrue(result["verified"])
        with self.assertRaises(SysadminError):
            self.expert.nix_operation("run-shell", "bash")

    def test_read_only_structured_diagnostics_do_not_expose_raw_shell(self):
        self.assertFalse(hasattr(self.expert, "shell"))
        self.assertEqual(self.expert.processes(1)["processes"][0]["pid"], 1)
        self.assertIn("memory", self.expert.resources())
        self.assertIn("interfaces", self.expert.network())

    def test_rule_inventory_contains_required_diagnostic_chains(self):
        rules = self.expert.rule_inventory()
        self.assertIn("service_failed", rules)
        self.assertIn("running_without_listener", rules)
        self.assertIn("dns_upstream_failure", rules)
        self.assertIn("nix_activation_failure", rules)
        self.assertTrue(all(rule["verification"] for rule in rules.values()))


if __name__ == "__main__":
    unittest.main()
