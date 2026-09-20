import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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
from zara_expert.language_composition import (
    CoreLanguageFamilyCompositionInvoker,
    LanguageFamilyCompositionInvoker,
)
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


class RecordingCoreRegistry:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def invoke(self, handle, operation, payload, *, limits):
        self.calls.append(
            {
                "handle": handle,
                "operation": operation,
                "payload": dict(payload),
                "limits": limits,
            }
        )
        if self.error is not None:
            raise self.error
        return self.result


class CoreLimits:
    def __init__(self, *, max_model_calls):
        self.max_model_calls = max_model_calls


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

    def test_core_bridge_routes_composition_through_canonical_registry(self):
        handle = SimpleNamespace(
            expert_id="zara:expert/nix",
            workspace="workspace-1",
        )
        result = SimpleNamespace(
            verdict=SimpleNamespace(value="succeeded"),
            data={
                "result": {
                    "kind": "nix-inspection",
                    "model_calls": 0,
                    "effect_receipts": [],
                    "evidence": ["raw:nix-evidence"],
                    "explanation": ["rule:nix-inspection"],
                }
            },
            evidence_refs=("ev:core:nix",),
            usage={"model_calls": 0},
            effect_receipts=(),
        )
        registry = RecordingCoreRegistry(result=result)
        activation_calls = []

        def activation_for(expert_id, fence):
            activation_calls.append((expert_id, fence.workspace_id))
            return handle

        invoker = CoreLanguageFamilyCompositionInvoker(
            registry,
            activation_for=activation_for,
            limits_factory=CoreLimits,
        )
        composer = MetaExpertComposer(invoker)
        budget = SharedSymbolicBudget(max_invocations=1, max_model_calls=0)

        with patch(
            "zara_expert.language_composition.make_language_expert_handler",
            side_effect=AssertionError("Core composition must not call the handler directly"),
        ):
            node = composer.invoke(
                "zara:expert/nix",
                "inspect",
                {"source": "{ x = 1; }", "source_generation": "generation-7"},
                budget=budget,
                fence=self._fence(),
            )

        self.assertEqual(node.status, "succeeded")
        self.assertEqual(node.evidence, ("ev:core:nix",))
        self.assertEqual(activation_calls, [("zara:expert/nix", "workspace-1")])
        self.assertEqual(len(registry.calls), 1)
        self.assertIs(registry.calls[0]["handle"], handle)
        self.assertEqual(registry.calls[0]["operation"], "inspect")
        self.assertEqual(registry.calls[0]["limits"].max_model_calls, 0)
        self.assertEqual(budget.invocations_used, 1)
        self.assertEqual(budget.evidence_used, 1)
        self.assertEqual(budget.model_calls_used, 0)

    def test_core_bridge_rejects_cross_workspace_activation_before_dispatch(self):
        handle = SimpleNamespace(
            expert_id="zara:expert/bash",
            workspace="workspace-other",
        )
        registry = RecordingCoreRegistry(
            result=SimpleNamespace(
                verdict=SimpleNamespace(value="succeeded"),
                data={},
                evidence_refs=(),
                usage={"model_calls": 0},
                effect_receipts=(),
            )
        )
        invoker = CoreLanguageFamilyCompositionInvoker(
            registry,
            activation_for=lambda _expert_id, _fence: handle,
            limits_factory=CoreLimits,
        )

        with self.assertRaisesRegex(CompositionError, "workspace"):
            invoker(
                "zara:expert/bash",
                "inspect",
                {"source": "true", "source_generation": "generation-7"},
                budget=SharedSymbolicBudget(),
                fence=self._fence(),
                parent_path=(),
            )
        self.assertEqual(registry.calls, [])

    def test_core_bridge_fails_closed_on_core_rejection(self):
        handle = SimpleNamespace(
            expert_id="zara:expert/bash",
            workspace="workspace-1",
        )
        registry = RecordingCoreRegistry(error=RuntimeError("stale activation generation"))
        invoker = CoreLanguageFamilyCompositionInvoker(
            registry,
            activation_for=lambda _expert_id, _fence: handle,
            limits_factory=CoreLimits,
        )

        with self.assertRaisesRegex(CompositionError, "stale activation generation"):
            invoker(
                "zara:expert/bash",
                "inspect",
                {"source": "true", "source_generation": "generation-7"},
                budget=SharedSymbolicBudget(),
                fence=self._fence(),
                parent_path=(),
            )
        self.assertEqual(len(registry.calls), 1)


if __name__ == "__main__":
    unittest.main()
