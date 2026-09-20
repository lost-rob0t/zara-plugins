import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertError
from zara_expert.lisp_family import make_lisp_expert_handler


class RecordingHost:
    def __init__(self):
        self.calls = []

    def query(self, namespace, predicate, arguments):
        self.calls.append((namespace, predicate, arguments))
        return {"ok": True, "results": ["symbolic-result"], "trace": []}

    def explain(self, namespace, predicate, arguments):
        self.calls.append((namespace, predicate, arguments))
        return {"ok": True, "results": ["symbolic-result"], "trace": []}


class LispHandlerArgumentAuthorityTests(unittest.TestCase):
    def test_core_handler_owns_registered_predicate_result_variable(self):
        host = RecordingHost()
        handler = make_lisp_expert_handler(host, "zara:expert/lisp")

        outcome = handler(
            expert_operation="structural.check",
            arguments=["(list)"],
        )

        self.assertEqual(outcome["verdict"], "succeeded")
        self.assertEqual(outcome["usage"], {"model_calls": 0})
        self.assertEqual(
            host.calls,
            [
                (
                    "lisp",
                    "structural_check",
                    ["(list)", {"var": "Result"}],
                )
            ],
        )

    def test_core_handler_rejects_caller_supplied_prolog_variable_before_dispatch(self):
        host = RecordingHost()
        handler = make_lisp_expert_handler(host, "zara:expert/lisp")

        with self.assertRaisesRegex(ExpertError, "result variable|ground"):
            handler(
                expert_operation="structural.check",
                arguments=[{"var": "Evidence"}],
            )

        self.assertEqual(host.calls, [])


if __name__ == "__main__":
    unittest.main()
