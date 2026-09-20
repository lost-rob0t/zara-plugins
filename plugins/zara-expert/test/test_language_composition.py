import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.composition import (
    CompositionError,
    InvocationFence,
    MetaExpertComposer,
    SharedSymbolicBudget,
)
from zara_expert.domain import ExpertHost
from zara_expert.language_composition import LanguageFamilyCompositionInvoker
from zara_expert.language_family import register_language_family


class RecordingBackend:
    def __init__(self, after_run=None):
        self.calls = []
        self.after_run = after_run

    def run(self, request):
        self.calls.append(dict(request))
        if self.after_run is not None:
            self.after_run()
        return {
            "ok": True,
            "results": ["evidence:language"],
            "trace": ["rule:language"],
        }


class VerdictBackend(RecordingBackend):
    def __init__(self, ok):
        super().__init__()
        self.ok = ok

    def run(self, request):
        self.calls.append(dict(request))
        return {
            "ok": self.ok,
            "results": ["evidence:partial"],
            "trace": ["rule:backend-verdict"],
        }


class LanguageCompositionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def _brain(self, name):
        path = self.root / f"{name}.pl"
        path.write_text("% language composition fixture\n", encoding="utf-8")
        return path

    @staticmethod
    def _fence(*, cancelled=lambda: False, current=lambda _workspace, _generation: True):
        return InvocationFence(
            workspace_id="workspace-1",
            workspace_generation=7,
            is_cancelled=cancelled,
            is_current_generation=current,
        )

    def _composer(self, backend, sources):
        host = ExpertHost(backend, state_root=self.root / f"state-{id(backend)}")
        register_language_family(host, sources)
        return MetaExpertComposer(LanguageFamilyCompositionInvoker(host))

    def test_prolog_python_and_nim_share_exact_zero_model_budget(self):
        backend = RecordingBackend()
        composer = self._composer(
            backend,
            {
                "prolog": [self._brain("prolog")],
                "python": [self._brain("python")],
                "nim": [self._brain("nim")],
            },
        )
        budget = SharedSymbolicBudget(max_invocations=3, max_evidence=3)
        fence = self._fence()

        fixtures = (
            ("zara:expert/prolog", "fact(a)."),
            ("zara:expert/python", "print('ok')"),
            ("zara:expert/nim", "proc main() = discard"),
        )
        for index, (expert_id, source) in enumerate(fixtures, start=1):
            node = composer.invoke(
                expert_id,
                "inspect",
                {
                    "source": source,
                    "source_generation": f"generation-{index}",
                },
                budget=budget,
                fence=fence,
            )
            self.assertEqual(node.status, "succeeded")
            self.assertEqual(node.evidence, ("evidence:language",))
            self.assertEqual(node.children, ())

        self.assertEqual(budget.invocations_used, 3)
        self.assertEqual(budget.evidence_used, 3)
        self.assertEqual(budget.max_model_calls, 0)
        self.assertEqual(budget.model_calls_used, 0)
        self.assertEqual(
            [call["capability"].predicate for call in backend.calls],
            ["language_evidence", "language_evidence", "language_evidence"],
        )

    def test_backend_failure_or_non_boolean_success_cannot_false_green_evidence(self):
        cases = ((False, "failed"), (1, "unknown"), ("true", "unknown"))
        for index, (backend_ok, expected_status) in enumerate(cases):
            with self.subTest(backend_ok=backend_ok):
                backend = VerdictBackend(backend_ok)
                composer = self._composer(
                    backend,
                    {"python": [self._brain(f"python-verdict-{index}")]},
                )
                budget = SharedSymbolicBudget(max_invocations=1, max_evidence=1)
                node = composer.invoke(
                    "zara:expert/python",
                    "inspect",
                    {
                        "source": "print('partial')",
                        "source_generation": f"generation-verdict-{index}",
                    },
                    budget=budget,
                    fence=self._fence(),
                )

                self.assertEqual(node.status, expected_status)
                self.assertEqual(node.evidence, ("evidence:partial",))
                self.assertEqual(budget.invocations_used, 1)
                self.assertEqual(budget.evidence_used, 1)
                self.assertEqual(budget.max_model_calls, 0)
                self.assertEqual(budget.model_calls_used, 0)

    def test_cancellation_after_backend_dispatch_fences_late_language_output(self):
        state = {"cancelled": False}
        backend = RecordingBackend(
            after_run=lambda: state.__setitem__("cancelled", True)
        )
        composer = self._composer(backend, {"python": [self._brain("python-cancel")]})
        budget = SharedSymbolicBudget()
        fence = self._fence(cancelled=lambda: state["cancelled"])

        with self.assertRaisesRegex(CompositionError, "cancelled"):
            composer.invoke(
                "zara:expert/python",
                "inspect",
                {"source": "print('late')", "source_generation": "generation-8"},
                budget=budget,
                fence=fence,
            )

        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(budget.invocations_used, 1)
        self.assertEqual(budget.evidence_used, 0)
        self.assertEqual(budget.model_calls_used, 0)

    def test_stale_generation_after_backend_dispatch_fences_late_language_output(self):
        state = {"current": True}
        backend = RecordingBackend(after_run=lambda: state.__setitem__("current", False))
        composer = self._composer(backend, {"nim": [self._brain("nim-stale")]})
        budget = SharedSymbolicBudget()
        fence = self._fence(current=lambda _workspace, _generation: state["current"])

        with self.assertRaisesRegex(CompositionError, "stale workspace generation"):
            composer.invoke(
                "zara:expert/nim",
                "diagnose",
                {
                    "source": "proc broken( = discard",
                    "source_generation": "generation-9",
                },
                budget=budget,
                fence=fence,
            )

        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(budget.invocations_used, 1)
        self.assertEqual(budget.evidence_used, 0)
        self.assertEqual(budget.model_calls_used, 0)

    def test_repair_apply_stays_on_canonical_effect_boundary(self):
        backend = RecordingBackend()
        composer = self._composer(backend, {"prolog": [self._brain("prolog-repair")]})
        budget = SharedSymbolicBudget()

        node = composer.invoke(
            "zara:expert/prolog",
            "repair.apply",
            {
                "repair": {"kind": "replace", "text": "fact(b)."},
                "expected_preimage": "sha256:fixture",
                "source_generation": "generation-10",
            },
            budget=budget,
            fence=self._fence(),
        )

        self.assertEqual(node.status, "blocked")
        self.assertEqual(node.data["reason"], "canonical-typed-edit-required")
        self.assertEqual(node.evidence, ())
        self.assertEqual(backend.calls, [])
        self.assertEqual(budget.model_calls_used, 0)

    def test_nonzero_or_boolean_model_ledger_fails_before_evidence_commit(self):
        backend = RecordingBackend()
        host = ExpertHost(backend, state_root=self.root / "ledger-state")
        invoker = LanguageFamilyCompositionInvoker(host)
        budget = SharedSymbolicBudget()

        for invalid in (1, False):
            with self.subTest(model_calls=invalid):
                fake_handler = lambda **_kwargs: {
                    "verdict": "succeeded",
                    "data": {},
                    "usage": {"model_calls": invalid},
                    "effect_receipts": [],
                }
                with patch(
                    "zara_expert.language_composition.make_language_expert_handler",
                    return_value=fake_handler,
                ):
                    with self.assertRaisesRegex(CompositionError, "model use"):
                        invoker(
                            "zara:expert/python",
                            "inspect",
                            {},
                            budget=budget,
                            fence=self._fence(),
                            parent_path=(),
                        )
        self.assertEqual(budget.model_calls_used, 0)
        self.assertEqual(backend.calls, [])


if __name__ == "__main__":
    unittest.main()
