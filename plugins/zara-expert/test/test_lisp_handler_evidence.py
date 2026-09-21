import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertError, ExpertHost
from zara_expert.lisp_family import make_lisp_expert_handler, register_lisp_family


DIALECT_CASES = (
    ("lisp", "zara:expert/lisp"),
    ("common-lisp", "zara:expert/common-lisp"),
    ("emacs-lisp", "zara:expert/emacs-lisp"),
)


class ResultOnlyBackend:
    def run(self, request):
        del request
        return {
            "ok": True,
            "results": ["repair(status(proposed),edit(insert,4,')'))"],
            "trace": [],
        }


class TraceBackend:
    def run(self, request):
        del request
        return {
            "ok": True,
            "results": ["symbolic-result"],
            "trace": ["provider:openai", "registered-predicate"],
        }


class CanonicalLookingHostTerm:
    def __str__(self):
        return f"evidence:lisp:sha256:{'0' * 64}"


class ForgedEvidenceString(str):
    def encode(self, encoding="utf-8", errors="strict"):
        del encoding, errors
        return b"forged-evidence-bytes"


class ObjectTraceBackend:
    def run(self, request):
        del request
        return {
            "ok": True,
            "results": ["symbolic-result"],
            "trace": [CanonicalLookingHostTerm()],
        }


class ObjectResultBackend:
    def run(self, request):
        del request
        return {
            "ok": True,
            "results": [CanonicalLookingHostTerm()],
            "trace": [],
        }


class StringSubclassTraceBackend:
    def run(self, request):
        del request
        return {
            "ok": True,
            "results": ["symbolic-result"],
            "trace": [ForgedEvidenceString("registered-predicate")],
        }


class StringSubclassResultBackend:
    def run(self, request):
        del request
        return {
            "ok": True,
            "results": [ForgedEvidenceString("symbolic-result")],
            "trace": [],
        }


class LispHandlerEvidenceTests(unittest.TestCase):
    def test_query_result_projects_bounded_content_addressed_evidence_ref(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            brain = root / "expert.pl"
            brain.write_text("% canonical symbolic fixture\n", encoding="utf-8")
            host = ExpertHost(ResultOnlyBackend(), state_root=root / "state")
            register_lisp_family(host, {"lisp": [brain]})

            result_term = "repair(status(proposed),edit(insert,4,')'))"
            outcome = make_lisp_expert_handler(host, "zara:expert/lisp")(
                expert_operation="repair.preview",
                arguments=["(x", "diagnostic:lisp:missing-close"],
            )

            digest = hashlib.sha256(result_term.encode("utf-8")).hexdigest()
            self.assertEqual(
                outcome["evidence_refs"],
                [f"evidence:lisp:sha256:{digest}"],
            )
            self.assertEqual(outcome["usage"], {"model_calls": 0})
            self.assertEqual(outcome["effect_receipts"], [])

    def test_trace_terms_are_content_addressed_instead_of_becoming_authority_shaped_refs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            brain = root / "expert.pl"
            brain.write_text("% canonical symbolic fixture\n", encoding="utf-8")
            host = ExpertHost(TraceBackend(), state_root=root / "state")
            register_lisp_family(host, {"lisp": [brain]})

            outcome = make_lisp_expert_handler(host, "zara:expert/lisp")(
                expert_operation="structural.check",
                arguments=["(x)"],
            )

            expected = [
                f"evidence:lisp:sha256:{hashlib.sha256(term.encode('utf-8')).hexdigest()}"
                for term in ("provider:openai", "registered-predicate")
            ]
            self.assertEqual(outcome["evidence_refs"], expected)
            self.assertNotIn("provider:openai", outcome["evidence_refs"])
            self.assertNotIn("registered-predicate", outcome["evidence_refs"])
            self.assertEqual(outcome["usage"], {"model_calls": 0})
            self.assertEqual(outcome["effect_receipts"], [])

    def test_registered_host_trace_rejects_stringifiable_object_for_every_lisp_dialect(self):
        for source_key, expert_id in DIALECT_CASES:
            with self.subTest(expert_id=expert_id), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                brain = root / "expert.pl"
                brain.write_text("% canonical symbolic fixture\n", encoding="utf-8")
                host = ExpertHost(ObjectTraceBackend(), state_root=root / "state")
                register_lisp_family(host, {source_key: [brain]})

                with self.assertRaisesRegex(ExpertError, "trace entries must be strings"):
                    make_lisp_expert_handler(host, expert_id)(
                        expert_operation="structural.check",
                        arguments=["(x)"],
                    )

    def test_registered_host_result_rejects_stringifiable_object_for_every_lisp_dialect(self):
        for source_key, expert_id in DIALECT_CASES:
            with self.subTest(expert_id=expert_id), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                brain = root / "expert.pl"
                brain.write_text("% canonical symbolic fixture\n", encoding="utf-8")
                host = ExpertHost(ObjectResultBackend(), state_root=root / "state")
                register_lisp_family(host, {source_key: [brain]})

                with self.assertRaisesRegex(ExpertError, "result entries must be strings"):
                    make_lisp_expert_handler(host, expert_id)(
                        expert_operation="structural.check",
                        arguments=["(x)"],
                    )

    def test_registered_host_trace_rejects_string_subclass_for_every_lisp_dialect(self):
        for source_key, expert_id in DIALECT_CASES:
            with self.subTest(expert_id=expert_id), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                brain = root / "expert.pl"
                brain.write_text("% canonical symbolic fixture\n", encoding="utf-8")
                host = ExpertHost(StringSubclassTraceBackend(), state_root=root / "state")
                register_lisp_family(host, {source_key: [brain]})

                with self.assertRaisesRegex(ExpertError, "trace entries must be strings"):
                    make_lisp_expert_handler(host, expert_id)(
                        expert_operation="structural.check",
                        arguments=["(x)"],
                    )

    def test_registered_host_result_rejects_string_subclass_for_every_lisp_dialect(self):
        for source_key, expert_id in DIALECT_CASES:
            with self.subTest(expert_id=expert_id), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                brain = root / "expert.pl"
                brain.write_text("% canonical symbolic fixture\n", encoding="utf-8")
                host = ExpertHost(StringSubclassResultBackend(), state_root=root / "state")
                register_lisp_family(host, {source_key: [brain]})

                with self.assertRaisesRegex(ExpertError, "result entries must be strings"):
                    make_lisp_expert_handler(host, expert_id)(
                        expert_operation="structural.check",
                        arguments=["(x)"],
                    )


if __name__ == "__main__":
    unittest.main()
