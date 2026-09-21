import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertError, ExpertHost
from zara_expert.lisp_family import (
    make_lisp_expert_handler,
    register_lisp_family,
    registered_predicates,
)


POSTCONDITIONS = {
    "common-lisp": "sbcl_fresh_reader_and_compile_evidence",
    "emacs-lisp": "emacs_fresh_reader_and_byte_compile_evidence",
}
CANDIDATE = "(defun demo (x) (list x))"
GENERATION = "buffer:9"


class StringifiableVerificationTerm:
    def __init__(self, expert_id, required_postcondition):
        self.expert_id = expert_id
        self.required_postcondition = required_postcondition

    def __str__(self):
        return (
            f"repair_verification(expert('{self.expert_id}'),verified(false),"
            f"required_postcondition({self.required_postcondition}))"
        )


class ObjectResultWithTraceBackend:
    def run(self, request):
        namespace = request["capability"].namespace
        expert_id = f"zara:expert/{namespace}"
        return {
            "ok": True,
            "results": [StringifiableVerificationTerm(expert_id, POSTCONDITIONS[namespace])],
            "trace": ["registered-predicate"],
        }


class EchoReceiptResolver:
    def __init__(self):
        self.calls = []

    def __call__(self, **query):
        self.calls.append(dict(query))
        return {
            "receipt_ref": "zara.verified-outcome/v1:outcome:postcondition/lisp-result-type-test",
            "expert_id": query["expert_id"],
            "source_generation": query["source_generation"],
            "candidate_sha256": query["candidate_sha256"],
            "required_postcondition": query["required_postcondition"],
            "verified": True,
            "fresh": True,
        }


class LispVerifyResultTypeTests(unittest.TestCase):
    def test_stringifiable_result_cannot_request_verified_postcondition(self):
        exports = [
            *(f"{predicate}/{arity}" for predicate, arity in registered_predicates().items()),
            "provider_policy/1",
            "max_model_calls/1",
            "model_calls/1",
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            host = ExpertHost(ObjectResultWithTraceBackend(), state_root=root / "state")
            sources = {}
            for key in POSTCONDITIONS:
                path = root / f"{key}.pl"
                path.write_text(
                    f":- module(fixture_{key.replace('-', '_')}, [{', '.join(exports)}]).\n"
                    "provider_policy(disabled).\n"
                    "max_model_calls(0).\n"
                    "model_calls(0).\n",
                    encoding="utf-8",
                )
                sources[key] = [path]
            register_lisp_family(host, sources)

            for key in POSTCONDITIONS:
                expert_id = f"zara:expert/{key}"
                resolver = EchoReceiptResolver()
                with self.subTest(expert_id=expert_id):
                    with self.assertRaisesRegex(ExpertError, "result entries must be strings"):
                        make_lisp_expert_handler(
                            host,
                            expert_id,
                            verified_outcome_resolver=resolver,
                        )(
                            expert_operation="repair.verify",
                            arguments=["(defun demo (x) (list x", CANDIDATE],
                            source_generation=GENERATION,
                        )
                    self.assertEqual(resolver.calls, [])


if __name__ == "__main__":
    unittest.main()
