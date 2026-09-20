import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertHost
from zara_expert.lisp_family import make_lisp_expert_handler, register_lisp_family


class MalformedOkBackend:
    def __init__(self, ok_value):
        self.ok_value = ok_value
        self.calls = []

    def run(self, request):
        self.calls.append(dict(request))
        return {
            "ok": self.ok_value,
            "results": ["symbolic-result"],
            "trace": ["registered-predicate"],
        }


class LispHandlerResultContractTests(unittest.TestCase):
    def _invoke_with_ok_value(self, ok_value):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            brain = root / "lisp.pl"
            brain.write_text("% canonical-brain-fixture\n", encoding="utf-8")
            backend = MalformedOkBackend(ok_value)
            host = ExpertHost(backend, state_root=root / "state")
            register_lisp_family(host, {"lisp": [brain]})
            handler = make_lisp_expert_handler(host, "zara:expert/lisp")
            outcome = handler(
                expert_operation="structural.check",
                arguments=["(list)", {"var": "Evidence"}],
            )
            return backend, outcome

    def test_only_exact_backend_true_can_be_rendered_as_success(self):
        backend, outcome = self._invoke_with_ok_value(True)
        self.assertEqual(outcome["verdict"], "succeeded")
        self.assertEqual(outcome["usage"], {"model_calls": 0})
        self.assertEqual(len(backend.calls), 1)

    def test_truthy_non_boolean_backend_status_cannot_false_green(self):
        for malformed in (1, "true", "false", [True], {"value": True}):
            with self.subTest(ok=malformed):
                backend, outcome = self._invoke_with_ok_value(malformed)
                self.assertEqual(outcome["verdict"], "unknown")
                self.assertEqual(outcome["usage"], {"model_calls": 0})
                self.assertEqual(outcome["effect_receipts"], [])
                self.assertEqual(len(backend.calls), 1)


if __name__ == "__main__":
    unittest.main()
