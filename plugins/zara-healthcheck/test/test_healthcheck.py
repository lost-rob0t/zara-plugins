import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_healthcheck.domain import HealthDomain, HealthError


class FakeClock:
    def __init__(self):
        self.value = 1000.0
    def now(self):
        self.value += 1.0
        return self.value


class SequenceProbe:
    def __init__(self, name, values):
        self.name = name
        self.values = list(values)
    def run(self):
        return self.values.pop(0)


class HealthDomainTest(unittest.TestCase):
    def test_normalizes_multiple_probe_classes(self):
        domain = HealthDomain({
            "memory": SequenceProbe("memory", [{"status":"healthy","value":42,"unit":"percent","evidence":{"available_mb":8000}}]),
            "dns": SequenceProbe("dns", [{"status":"healthy","value":18,"unit":"ms","evidence":{"target":"resolver.test"}}]),
        }, clock=FakeClock())
        snapshot = domain.poll()
        self.assertEqual(set(snapshot), {"memory", "dns"})
        self.assertEqual(snapshot["dns"]["unit"], "ms")
        self.assertEqual(snapshot["memory"]["status"], "healthy")

    def test_failed_probe_becomes_unknown_with_evidence(self):
        class Broken:
            def run(self):
                raise RuntimeError("offline")
        domain = HealthDomain({"svc": Broken()}, clock=FakeClock())
        result = domain.poll()["svc"]
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["evidence"]["error_type"], "RuntimeError")
        self.assertNotIn("offline", str(result))

    def test_hysteresis_requires_repeated_degradation_and_dedupes_events(self):
        probe = SequenceProbe("disk", [
            {"status":"healthy","value":40,"unit":"percent","evidence":{}},
            {"status":"unhealthy","value":96,"unit":"percent","evidence":{}},
            {"status":"unhealthy","value":97,"unit":"percent","evidence":{}},
            {"status":"unhealthy","value":98,"unit":"percent","evidence":{}},
        ])
        domain = HealthDomain({"disk": probe}, clock=FakeClock(), hysteresis_count=2)
        domain.poll()
        domain.poll()
        self.assertEqual(domain.state()["disk"]["status"], "healthy")
        domain.poll()
        self.assertEqual(domain.state()["disk"]["status"], "unhealthy")
        events = domain.drain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["to"], "unhealthy")
        domain.poll()
        self.assertEqual(domain.drain_events(), [])

    def test_history_is_bounded(self):
        probe = SequenceProbe("cpu", [{"status":"healthy","value":n,"unit":"percent","evidence":{}} for n in range(10)])
        domain = HealthDomain({"cpu": probe}, clock=FakeClock(), history_limit=3)
        for _ in range(10):
            domain.poll()
        self.assertEqual(len(domain.history("cpu")), 3)
        self.assertEqual(domain.history("cpu")[-1]["value"], 9)

    def test_export_facts_preserves_unknown_and_evidence(self):
        probe = SequenceProbe("http-api", [{"status":"degraded","value":800,"unit":"ms","evidence":{"target_id":"api-main","code":200}}])
        domain = HealthDomain({"http-api": probe}, clock=FakeClock(), hysteresis_count=1)
        domain.poll()
        facts = domain.export_facts()
        self.assertEqual(facts[0]["predicate"], "health_status")
        self.assertEqual(facts[0]["args"][0], "http-api")
        self.assertEqual(facts[0]["args"][1], "degraded")
        self.assertIn("evidence", facts[0])

    def test_probe_and_payload_bounds_fail_closed(self):
        with self.assertRaises(HealthError):
            HealthDomain({str(i): SequenceProbe(str(i), []) for i in range(300)})
        huge = {"status":"healthy","value":1,"unit":"x","evidence":{"blob":"x" * 100000}}
        domain = HealthDomain({"x": SequenceProbe("x", [huge])}, max_evidence_bytes=1024)
        self.assertEqual(domain.poll()["x"]["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
