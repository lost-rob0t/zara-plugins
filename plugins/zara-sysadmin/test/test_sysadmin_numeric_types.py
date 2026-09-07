import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_sysadmin.domain import SysadminError, SysadminExpert


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def journal(self, unit, limit):
        self.calls.append(("journal", unit, limit))
        return []

    def listener(self, port):
        self.calls.append(("listener", port))
        return {"port": port, "listening": False}

    def process_summary(self, limit):
        self.calls.append(("process_summary", limit))
        return []

    def service_status(self, unit):
        self.calls.append(("service_status", unit))
        return {"active": True, "result": "success", "substate": "running"}

    def nix_generations(self, limit):
        self.calls.append(("nix_generations", limit))
        return []


class SysadminNumericTypeTests(unittest.TestCase):
    def test_constructor_limits_reject_coercive_descriptors(self):
        for key in ("max_log_lines", "max_processes"):
            for value in (True, False, "10", 10.5):
                with self.subTest(key=key, value=value):
                    kwargs = {"max_log_lines": 32, "max_processes": 16, key: value}
                    with self.assertRaises(SysadminError):
                        SysadminExpert(RecordingBackend(), **kwargs)

    def test_query_limits_reject_coercive_descriptors_before_backend_dispatch(self):
        backend = RecordingBackend()
        expert = SysadminExpert(backend, max_log_lines=32, max_processes=16)
        operations = (
            lambda value: expert.journal("demo.service", value),
            lambda value: expert.processes(value),
            lambda value: expert.nix_generations(value),
        )
        for operation in operations:
            for value in (True, False, "1", 1.5):
                with self.subTest(operation=operation, value=value):
                    backend.calls.clear()
                    with self.assertRaises(SysadminError):
                        operation(value)
                    self.assertEqual([], backend.calls)

    def test_service_port_rejects_coercive_descriptors_before_backend_dispatch(self):
        backend = RecordingBackend()
        expert = SysadminExpert(backend)
        for value in (True, False, "8080", 8080.5):
            with self.subTest(value=value):
                backend.calls.clear()
                with self.assertRaises(SysadminError):
                    expert.diagnose_service_port("web.service", value)
                self.assertEqual([], backend.calls)

    def test_actual_integers_still_work(self):
        backend = RecordingBackend()
        expert = SysadminExpert(backend, max_log_lines=32, max_processes=16)
        self.assertEqual(0, expert.journal("demo.service", 1)["count"])
        self.assertEqual(0, expert.processes(1)["count"])
        self.assertEqual([], expert.nix_generations(1)["generations"])
        self.assertEqual(8080, expert.diagnose_service_port("web.service", 8080)["evidence"]["listener"]["port"])


if __name__ == "__main__":
    unittest.main()
