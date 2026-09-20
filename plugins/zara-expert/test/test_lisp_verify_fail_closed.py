import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertHost
from zara_expert.lisp_family import (
    lisp_family_specs,
    make_lisp_expert_handler,
    register_lisp_family,
    registered_predicates,
)


class UnverifiedRepairBackend:
    def __init__(self):
        self.calls = []

    def run(self, request):
        self.calls.append(dict(request))
        return {
            "ok": True,
            "results": [
                "repair_verification(expert('zara:expert/lisp'),verified(false),"
                "reason(fresh_dialect_reader_postcondition_required))"
            ],
            "trace": ["registered-predicate"],
        }


class LispRepairVerificationFailClosedTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.backend = UnverifiedRepairBackend()
        self.host = ExpertHost(self.backend, state_root=self.root / "state")

        exports = [
            *(f"{predicate}/{arity}" for predicate, arity in registered_predicates().items()),
            "provider_policy/1",
            "max_model_calls/1",
            "model_calls/1",
        ]
        sources = {}
        for spec in lisp_family_specs():
            path = self.root / f"{spec.key}.pl"
            module_name = f"fixture_{spec.key.replace('-', '_')}"
            path.write_text(
                f":- module({module_name}, [{', '.join(exports)}]).\n"
                "provider_policy(disabled).\n"
                "max_model_calls(0).\n"
                "model_calls(0).\n",
                encoding="utf-8",
            )
            sources[spec.key] = [path]
        register_lisp_family(self.host, sources)

    def tearDown(self):
        self.temporary.cleanup()

    def test_query_completion_cannot_claim_verified_repair_success(self):
        for spec in lisp_family_specs():
            with self.subTest(expert=spec.expert_id):
                handler = make_lisp_expert_handler(self.host, spec.expert_id)
                outcome = handler(
                    expert_operation="repair.verify",
                    arguments=["(defun demo ()", "(defun demo ())"],
                )

                self.assertEqual(outcome["verdict"], "unknown")
                self.assertEqual(outcome["usage"], {"model_calls": 0})
                self.assertEqual(outcome["effect_receipts"], [])
                self.assertTrue(outcome["evidence_refs"])

        self.assertEqual(len(self.backend.calls), len(lisp_family_specs()))
        self.assertTrue(
            all(call["capability"].predicate == "verify_repair" for call in self.backend.calls)
        )


if __name__ == "__main__":
    unittest.main()
