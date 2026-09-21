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


class ExpandingStringList(list):
    """Lie about boundedness, then change terms between validation and hashing."""

    def __init__(self):
        super().__init__(["registered-predicate"])
        self._iterations = 0

    def __len__(self):
        return 1

    def __iter__(self):
        self._iterations += 1
        if self._iterations == 1:
            return iter(("registered-predicate",))
        return iter(tuple(f"expanded-term-{index}" for index in range(33)))


class ExpandingTraceBackend:
    def run(self, request):
        del request
        return {
            "ok": True,
            "results": ["symbolic-result"],
            "trace": ExpandingStringList(),
        }


class ExpandingResultBackend:
    def run(self, request):
        del request
        return {
            "ok": True,
            "results": ExpandingStringList(),
            "trace": [],
        }


class LispEvidenceContainerIdentityTests(unittest.TestCase):
    def _assert_sequence_subclass_rejected(self, backend_type, expected_message):
        for source_key, expert_id in DIALECT_CASES:
            with self.subTest(expert_id=expert_id), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                brain = root / "expert.pl"
                brain.write_text("% canonical symbolic fixture\n", encoding="utf-8")
                host = ExpertHost(backend_type(), state_root=root / "state")
                register_lisp_family(host, {source_key: [brain]})

                with self.assertRaisesRegex(ExpertError, expected_message):
                    make_lisp_expert_handler(host, expert_id)(
                        expert_operation="structural.check",
                        arguments=["(x)"],
                    )

    def test_trace_sequence_subclass_cannot_bypass_bounded_evidence_projection(self):
        self._assert_sequence_subclass_rejected(
            ExpandingTraceBackend,
            "trace must be a built-in list or tuple",
        )

    def test_result_sequence_subclass_cannot_bypass_bounded_evidence_projection(self):
        self._assert_sequence_subclass_rejected(
            ExpandingResultBackend,
            "results must be a built-in list or tuple",
        )


if __name__ == "__main__":
    unittest.main()
