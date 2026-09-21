import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertError
from zara_expert.lisp_family import make_lisp_expert_handler


class NeverRunHost:
    def query(self, *args, **kwargs):
        raise AssertionError("malformed repair.verify input reached registered host")

    def explain(self, *args, **kwargs):
        raise AssertionError("malformed repair.verify input reached registered host")


class ForgedText(str):
    def encode(self, encoding="utf-8", errors="strict"):
        return b"forged-candidate-bytes"


class ForgedArguments(list):
    pass


class LispVerifyInputIdentityTests(unittest.TestCase):
    def _handler(self, expert_id):
        return make_lisp_expert_handler(NeverRunHost(), expert_id)

    def test_dialect_verify_rejects_string_subclass_candidate_before_host(self):
        for expert_id in (
            "zara:expert/common-lisp",
            "zara:expert/emacs-lisp",
        ):
            with self.subTest(expert=expert_id):
                handler = self._handler(expert_id)
                with self.assertRaisesRegex(ExpertError, "ground strings"):
                    handler(
                        expert_operation="repair.verify",
                        arguments=[
                            "(defun demo (x) (list x",
                            ForgedText("(defun demo (x) (list x))"),
                        ],
                        source_generation="buffer:8",
                    )

    def test_dialect_verify_rejects_string_subclass_generation_before_host(self):
        for expert_id in (
            "zara:expert/common-lisp",
            "zara:expert/emacs-lisp",
        ):
            with self.subTest(expert=expert_id):
                handler = self._handler(expert_id)
                with self.assertRaisesRegex(ExpertError, "source_generation"):
                    handler(
                        expert_operation="repair.verify",
                        arguments=[
                            "(defun demo (x) (list x",
                            "(defun demo (x) (list x))",
                        ],
                        source_generation=ForgedText("buffer:8"),
                    )

    def test_dialect_verify_rejects_list_subclass_before_host(self):
        for expert_id in (
            "zara:expert/common-lisp",
            "zara:expert/emacs-lisp",
        ):
            with self.subTest(expert=expert_id):
                handler = self._handler(expert_id)
                with self.assertRaisesRegex(ExpertError, "arguments must be a list"):
                    handler(
                        expert_operation="repair.verify",
                        arguments=ForgedArguments(
                            [
                                "(defun demo (x) (list x",
                                "(defun demo (x) (list x))",
                            ]
                        ),
                        source_generation="buffer:8",
                    )


if __name__ == "__main__":
    unittest.main()
