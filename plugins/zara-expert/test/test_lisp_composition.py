import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert import LispFamilyCompositionInvoker
from zara_expert.composition import (
    CompositionError,
    InvocationFence,
    MetaExpertComposer,
    SharedSymbolicBudget,
)
from zara_expert.domain import ExpertError, ExpertHost
from zara_expert.lisp_family import register_lisp_family


class RecordingBackend:
    def __init__(self, *, ok=True):
        self.requests = []
        self.ok = ok

    def run(self, request):
        self.requests.append(request)
        capability = request["capability"]
        return {
            "ok": self.ok,
            "results": [{"repair": "(print 1)"}],
            "trace": [
                f"{capability.namespace}:{capability.predicate}/{capability.arity}"
            ],
        }


def current_fence():
    return InvocationFence(
        workspace_id="project",
        workspace_generation=4,
        is_cancelled=lambda: False,
        is_current_generation=lambda workspace, generation: (
            workspace == "project" and generation == 4
        ),
    )


class LispCompositionTests(unittest.TestCase):
    def make_host(self, root, backend):
        brain = root / "expert.pl"
        brain.write_text("% canonical symbolic fixture\n", encoding="utf-8")
        host = ExpertHost(backend, state_root=root / "state")
        registered = register_lisp_family(
            host,
            {
                "lisp": [brain],
                "common-lisp": [brain],
                "emacs-lisp": [brain],
            },
        )
        self.assertEqual(registered, frozenset({"lisp", "common-lisp", "emacs-lisp"}))
        return host

    def test_common_lisp_repair_delegates_to_generic_lisp_with_one_shared_zero_model_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backend = RecordingBackend()
            host = self.make_host(root, backend)
            budget = SharedSymbolicBudget(max_invocations=2, max_depth=1, max_model_calls=0)

            tree = MetaExpertComposer(LispFamilyCompositionInvoker(host)).invoke(
                "zara:expert/common-lisp",
                "repair.preview",
                {
                    "arguments": [
                        "(print 1",
                        "missing-close-paren",
                    ]
                },
                budget=budget,
                fence=current_fence(),
            )

            self.assertEqual(tree.expert_id, "zara:expert/common-lisp")
            self.assertEqual(tree.status, "unknown")
            self.assertEqual(
                tree.data,
                {
                    "delegated_to": "zara:expert/lisp",
                    "delegation_required": True,
                },
            )
            self.assertEqual(len(tree.children), 1)
            child = tree.children[0]
            self.assertEqual(child.expert_id, "zara:expert/lisp")
            self.assertEqual(child.operation, "repair.preview")
            self.assertEqual(child.status, "succeeded")
            self.assertEqual(child.evidence, ("lisp:preview_repair/3",))
            self.assertEqual(child.data["result"]["results"], [{"repair": "(print 1)"}])
            self.assertEqual(budget.invocations_used, 2)
            self.assertEqual(budget.evidence_used, 1)
            self.assertEqual(budget.model_calls_used, 0)
            self.assertEqual(len(backend.requests), 1)
            capability = backend.requests[0]["capability"]
            self.assertEqual(capability.namespace, "lisp")
            self.assertEqual(capability.predicate, "preview_repair")
            self.assertEqual(capability.arity, 3)
            self.assertEqual(
                backend.requests[0]["arguments"],
                ["(print 1", "missing-close-paren", {"var": "Result"}],
            )

    def test_failed_generic_lisp_child_cannot_false_green_dialect_repair(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backend = RecordingBackend(ok=False)
            host = self.make_host(root, backend)
            budget = SharedSymbolicBudget(max_invocations=2, max_depth=1, max_model_calls=0)

            tree = MetaExpertComposer(LispFamilyCompositionInvoker(host)).invoke(
                "zara:expert/emacs-lisp",
                "repair.preview",
                {
                    "arguments": [
                        "(message \"broken\"",
                        "missing-close-paren",
                    ]
                },
                budget=budget,
                fence=current_fence(),
            )

            self.assertEqual(tree.status, "unknown")
            self.assertEqual(len(tree.children), 1)
            self.assertEqual(tree.children[0].status, "failed")
            self.assertEqual(tree.children[0].evidence, ("lisp:preview_repair/3",))
            self.assertEqual(budget.invocations_used, 2)
            self.assertEqual(budget.model_calls_used, 0)
            self.assertEqual(len(backend.requests), 1)
            self.assertEqual(
                backend.requests[0]["arguments"],
                ["(message \"broken\"", "missing-close-paren", {"var": "Result"}],
            )

    def test_composition_injects_result_variable_for_public_predicate_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backend = RecordingBackend()
            host = self.make_host(root, backend)

            tree = MetaExpertComposer(LispFamilyCompositionInvoker(host)).invoke(
                "zara:expert/lisp",
                "structural.check",
                {"arguments": ["(ok)"]},
                budget=SharedSymbolicBudget(max_model_calls=0),
                fence=current_fence(),
            )

            self.assertEqual(tree.status, "succeeded")
            self.assertEqual(tree.evidence, ("lisp:structural_check/2",))
            self.assertEqual(len(backend.requests), 1)
            self.assertEqual(
                backend.requests[0]["arguments"],
                ["(ok)", {"var": "Result"}],
            )

    def test_caller_cannot_smuggle_result_variable_through_composition(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backend = RecordingBackend()
            host = self.make_host(root, backend)

            with self.assertRaisesRegex(CompositionError, "caller-supplied Prolog result variable"):
                MetaExpertComposer(LispFamilyCompositionInvoker(host)).invoke(
                    "zara:expert/lisp",
                    "repair.preview",
                    {
                        "arguments": [
                            "(print 1",
                            {"var": "Repair"},
                        ]
                    },
                    budget=SharedSymbolicBudget(max_model_calls=0),
                    fence=current_fence(),
                )

            self.assertEqual(backend.requests, [])

    def test_public_input_cannot_select_a_predicate_or_goal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backend = RecordingBackend()
            host = self.make_host(root, backend)

            with self.assertRaisesRegex(CompositionError, "unsupported fields"):
                MetaExpertComposer(LispFamilyCompositionInvoker(host)).invoke(
                    "zara:expert/lisp",
                    "structural.check",
                    {
                        "arguments": ["(ok)"],
                        "predicate": "shell",
                        "goal": "halt",
                    },
                    budget=SharedSymbolicBudget(max_model_calls=0),
                    fence=current_fence(),
                )

            self.assertEqual(backend.requests, [])

    def test_repair_apply_preserves_public_schema_but_still_requires_effect_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backend = RecordingBackend()
            host = self.make_host(root, backend)

            with self.assertRaisesRegex(ExpertError, "canonical typed edit/effect path"):
                MetaExpertComposer(LispFamilyCompositionInvoker(host)).invoke(
                    "zara:expert/lisp",
                    "repair.apply",
                    {
                        "repair": {"replacement": "(print 1)"},
                        "expected_preimage": "(print 1",
                        "source_generation": "project:4",
                    },
                    budget=SharedSymbolicBudget(max_model_calls=0),
                    fence=current_fence(),
                )

            self.assertEqual(backend.requests, [])


if __name__ == "__main__":
    unittest.main()
