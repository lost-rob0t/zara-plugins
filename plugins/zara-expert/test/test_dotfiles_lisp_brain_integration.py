import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.backend import SwiplBackend
from zara_expert.domain import ExpertHost
from zara_expert.lisp_family import make_lisp_expert_handler, register_lisp_family
from zara_expert.lisp_source_contract import validate_lisp_source_contracts


DOTFILES_ROOT = os.environ.get("ZARA_DOTFILES_ROOT")


@unittest.skipUnless(DOTFILES_ROOT, "canonical Dotfiles checkout not provided")
class DotfilesLispBrainIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        cls.expert_root = cls.dotfiles_root / ".zara" / "experts"
        cls.sources = {
            key: [cls.expert_root / key / "kb" / "expert.pl"]
            for key in ("lisp", "common-lisp", "emacs-lisp")
        }
        for key, paths in cls.sources.items():
            for path in paths:
                if not path.is_file():
                    raise AssertionError(f"missing canonical {key} brain: {path}")
        validate_lisp_source_contracts(cls.sources)
        if not SwiplBackend.available():
            raise AssertionError("SWI-Prolog is required for canonical Lisp brain integration")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.host = ExpertHost(
            SwiplBackend(),
            state_root=Path(self.temporary.name) / "state",
            query_timeout_seconds=5.0,
        )
        registered = register_lisp_family(self.host, self.sources)
        self.assertEqual(
            registered,
            frozenset({"lisp", "common-lisp", "emacs-lisp"}),
        )

    def tearDown(self):
        self.temporary.cleanup()

    def _assert_zero_model(self, outcome):
        self.assertEqual(outcome["usage"], {"model_calls": 0})
        self.assertEqual(outcome["effect_receipts"], [])

    def _invoke(self, expert_id, operation, arguments):
        handler = make_lisp_expert_handler(self.host, expert_id)
        outcome = handler(expert_operation=operation, arguments=arguments)
        self._assert_zero_model(outcome)
        self.assertEqual(outcome["verdict"], "succeeded")
        self.assertTrue(outcome["data"]["result"]["results"])
        return outcome

    def test_real_dotfiles_brains_match_and_diagnose_without_models(self):
        cases = (
            (
                "zara:expert/lisp",
                "src/demo.lisp",
                "(defun demo (x) (list x",
            ),
            (
                "zara:expert/common-lisp",
                "src/demo.cl",
                "(defun demo (x) (list x",
            ),
            (
                "zara:expert/emacs-lisp",
                "lisp/demo.el",
                "(defun demo (x) (list x ?\\()",
            ),
        )
        for expert_id, path, source in cases:
            with self.subTest(expert=expert_id):
                matched = self._invoke(
                    expert_id,
                    "match",
                    [path],
                )
                rendered_match = " ".join(matched["data"]["result"]["results"])
                self.assertIn(f"applicability('{expert_id}',true)", rendered_match)

                checked = self._invoke(
                    expert_id,
                    "structural.check",
                    [source],
                )
                self.assertIn("unmatched_open", " ".join(checked["data"]["result"]["results"]))

                diagnosed = self._invoke(
                    expert_id,
                    "structural.diagnose",
                    [source],
                )
                self.assertIn("diagnosis", " ".join(diagnosed["data"]["result"]["results"]))

    def test_base_lisp_missing_paren_preview_is_reader_aware_and_effect_free(self):
        source = '(list "text )" ; ignored )\n #| ignored ( |# value'
        preview = self._invoke(
            "zara:expert/lisp",
            "repair.preview",
            [source, "diagnostic:lisp:missing-close"],
        )
        rendered = " ".join(preview["data"]["result"]["results"])
        self.assertIn("status(proposed)", rendered)
        self.assertIn("edit(insert", rendered)
        self.assertIn("fresh_dialect_reader_postcondition", rendered)

    def test_dialect_verify_requires_fresh_reader_postcondition(self):
        cases = (
            (
                "zara:expert/common-lisp",
                "(defun demo (x) (list x",
                "(defun demo (x) (list x))",
                "sbcl_fresh_reader_and_compile_evidence",
            ),
            (
                "zara:expert/emacs-lisp",
                "(defun demo (x) (list x",
                "(defun demo (x) (list x))",
                "emacs_fresh_reader_and_byte_compile_evidence",
            ),
        )
        for expert_id, original, candidate, postcondition in cases:
            with self.subTest(expert=expert_id):
                verified = self._invoke(
                    expert_id,
                    "repair.verify",
                    [original, candidate],
                )
                rendered = " ".join(verified["data"]["result"]["results"])
                self.assertIn("verified(false)", rendered)
                self.assertIn(postcondition, rendered)

    def test_repair_apply_is_blocked_before_backend_or_filesystem_effects(self):
        handler = make_lisp_expert_handler(self.host, "zara:expert/lisp")
        outcome = handler(
            expert_operation="repair.apply",
            repair={"kind": "insert", "offset": 4, "text": ")"},
            expected_preimage="sha256:fixture",
            source_generation="buffer:1",
        )
        self._assert_zero_model(outcome)
        self.assertEqual(outcome["verdict"], "blocked")
        self.assertEqual(outcome["data"]["reason"], "canonical-typed-edit-required")


if __name__ == "__main__":
    unittest.main()
