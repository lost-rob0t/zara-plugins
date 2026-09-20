import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.lisp_family import make_lisp_expert_handler


class ResultHost:
    def __init__(self, ok):
        self.ok = ok
        self.calls = []

    def query(self, namespace, predicate, arguments):
        self.calls.append((namespace, predicate, arguments))
        return {
            "ok": self.ok,
            "results": [],
            "trace": [f"{namespace}:{predicate}"],
        }

    def explain(self, namespace, predicate, arguments):
        self.calls.append((namespace, predicate, arguments))
        return {
            "ok": self.ok,
            "results": [],
            "trace": [f"{namespace}:{predicate}"],
        }


class LispHandlerStatusTests(unittest.TestCase):
    def test_literal_false_backend_result_is_failed_not_unknown(self):
        host = ResultHost(False)
        handler = make_lisp_expert_handler(host, "zara:expert/lisp")

        outcome = handler(
            expert_operation="structural.check",
            arguments=["(broken", {"var": "Evidence"}],
        )

        self.assertEqual(outcome["verdict"], "failed")
        self.assertEqual(outcome["usage"], {"model_calls": 0})
        self.assertEqual(outcome["effect_receipts"], [])
        self.assertEqual(len(host.calls), 1)

    def test_truthy_non_boolean_backend_result_cannot_manufacture_success(self):
        host = ResultHost("false")
        handler = make_lisp_expert_handler(host, "zara:expert/lisp")

        outcome = handler(
            expert_operation="structural.check",
            arguments=["(broken", {"var": "Evidence"}],
        )

        self.assertEqual(outcome["verdict"], "unknown")
        self.assertEqual(outcome["usage"], {"model_calls": 0})
        self.assertEqual(outcome["effect_receipts"], [])
        self.assertEqual(len(host.calls), 1)


if __name__ == "__main__":
    unittest.main()
