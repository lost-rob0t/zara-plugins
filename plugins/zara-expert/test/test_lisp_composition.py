import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert import CoreLispFamilyCompositionInvoker, LispFamilyCompositionInvoker
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


class RecordingCoreRegistry:
    def __init__(self, result=None, *, error=None, after_invoke=None):
        self.result = result
        self.error = error
        self.after_invoke = after_invoke
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
        if self.after_invoke is not None:
            self.after_invoke()
        if self.error is not None:
            raise self.error
        return self.result


class CoreLimits:
    def __init__(self, *, max_model_calls):
        self.max_model_calls = max_model_calls


def current_fence():
    return InvocationFence(
        workspace_id="project",
        workspace_generation=4,
        is_cancelled=lambda: False,
        is_current_generation=lambda workspace, generation: (
            workspace == "project" and generation == 4
        ),
    )


def core_result(
    *,
    status="succeeded",
    data=None,
    evidence_refs=("ev:core:lisp",),
    model_calls=0,
    effect_receipts=(),
):
    if data is None:
        data = {
            "result": {
                "ok": True,
                "results": [{"repair": "(print 1)"}],
                "trace": ["lisp:preview_repair/3"],
            }
        }
    return SimpleNamespace(
        verdict=SimpleNamespace(value=status),
        data=data,
        evidence_refs=evidence_refs,
        usage={"model_calls": model_calls},
        effect_receipts=effect_receipts,
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

    def test_core_bridge_routes_generic_lisp_through_canonical_registry(self):
        handle = SimpleNamespace(expert_id="zara:expert/lisp", workspace="project")
        registry = RecordingCoreRegistry(result=core_result())
        activation_calls = []

        def activation_for(expert_id, fence):
            activation_calls.append((expert_id, fence.workspace_id))
            return handle

        invoker = CoreLispFamilyCompositionInvoker(
            registry,
            activation_for=activation_for,
            limits_factory=CoreLimits,
        )
        composer = MetaExpertComposer(invoker)
        budget = SharedSymbolicBudget(max_invocations=1, max_model_calls=0)

        with patch(
            "zara_expert.lisp_composition.make_lisp_expert_handler",
            side_effect=AssertionError("Core composition must not call the local handler"),
        ):
            node = composer.invoke(
                "zara:expert/lisp",
                "structural.check",
                {"arguments": ["(ok)"]},
                budget=budget,
                fence=current_fence(),
            )

        self.assertEqual(node.status, "succeeded")
        self.assertEqual(node.evidence, ("ev:core:lisp",))
        self.assertEqual(activation_calls, [("zara:expert/lisp", "project")])
        self.assertEqual(len(registry.calls), 1)
        self.assertIs(registry.calls[0]["handle"], handle)
        self.assertEqual(registry.calls[0]["operation"], "structural.check")
        self.assertEqual(registry.calls[0]["payload"], {"arguments": ["(ok)"]})
        self.assertEqual(registry.calls[0]["limits"].max_model_calls, 0)
        self.assertEqual(budget.invocations_used, 1)
        self.assertEqual(budget.evidence_used, 1)
        self.assertEqual(budget.model_calls_used, 0)

    def test_core_bridge_routes_dialect_repair_child_through_core_shared_budget(self):
        handles = {
            expert_id: SimpleNamespace(expert_id=expert_id, workspace="project")
            for expert_id in ("zara:expert/common-lisp", "zara:expert/lisp")
        }
        registry = RecordingCoreRegistry(result=core_result())
        activation_calls = []

        def activation_for(expert_id, fence):
            activation_calls.append((expert_id, fence.workspace_id))
            return handles[expert_id]

        composer = MetaExpertComposer(
            CoreLispFamilyCompositionInvoker(
                registry,
                activation_for=activation_for,
                limits_factory=CoreLimits,
            )
        )
        budget = SharedSymbolicBudget(max_invocations=2, max_depth=1, max_model_calls=0)

        tree = composer.invoke(
            "zara:expert/common-lisp",
            "repair.preview",
            {"arguments": ["(print 1", "missing-close-paren"]},
            budget=budget,
            fence=current_fence(),
        )

        self.assertEqual(tree.status, "unknown")
        self.assertEqual(len(tree.children), 1)
        child = tree.children[0]
        self.assertEqual(child.expert_id, "zara:expert/lisp")
        self.assertEqual(child.status, "succeeded")
        self.assertEqual(child.evidence, ("ev:core:lisp",))
        self.assertEqual(
            activation_calls,
            [
                ("zara:expert/common-lisp", "project"),
                ("zara:expert/lisp", "project"),
            ],
        )
        self.assertEqual(len(registry.calls), 1)
        self.assertEqual(registry.calls[0]["handle"].expert_id, "zara:expert/lisp")
        self.assertEqual(registry.calls[0]["operation"], "repair.preview")
        self.assertEqual(
            registry.calls[0]["payload"],
            {"arguments": ["(print 1", "missing-close-paren"]},
        )
        self.assertEqual(registry.calls[0]["limits"].max_model_calls, 0)
        self.assertEqual(budget.invocations_used, 2)
        self.assertEqual(budget.evidence_used, 1)
        self.assertEqual(budget.model_calls_used, 0)

    def test_core_bridge_repair_apply_stays_inside_core_effect_boundary(self):
        handle = SimpleNamespace(expert_id="zara:expert/lisp", workspace="project")
        registry = RecordingCoreRegistry(
            result=core_result(
                status="blocked",
                data={
                    "reason": "canonical-typed-edit-required",
                    "expert_id": "zara:expert/lisp",
                },
                evidence_refs=(),
            )
        )
        invoker = CoreLispFamilyCompositionInvoker(
            registry,
            activation_for=lambda _expert_id, _fence: handle,
            limits_factory=CoreLimits,
        )
        budget = SharedSymbolicBudget(max_model_calls=0)

        node = MetaExpertComposer(invoker).invoke(
            "zara:expert/lisp",
            "repair.apply",
            {
                "repair": {"replacement": "(print 1)"},
                "expected_preimage": "(print 1",
                "source_generation": "project:4",
            },
            budget=budget,
            fence=current_fence(),
        )

        self.assertEqual(node.status, "blocked")
        self.assertEqual(node.data["reason"], "canonical-typed-edit-required")
        self.assertEqual(len(registry.calls), 1)
        self.assertEqual(registry.calls[0]["operation"], "repair.apply")
        self.assertEqual(registry.calls[0]["limits"].max_model_calls, 0)
        self.assertEqual(budget.model_calls_used, 0)

    def test_core_bridge_rejects_cross_workspace_activation_before_dispatch(self):
        handle = SimpleNamespace(
            expert_id="zara:expert/emacs-lisp",
            workspace="other-project",
        )
        registry = RecordingCoreRegistry(result=core_result())
        invoker = CoreLispFamilyCompositionInvoker(
            registry,
            activation_for=lambda _expert_id, _fence: handle,
            limits_factory=CoreLimits,
        )

        with self.assertRaisesRegex(CompositionError, "workspace"):
            invoker(
                "zara:expert/emacs-lisp",
                "structural.check",
                {"arguments": ["(message \"ok\")"]},
                budget=SharedSymbolicBudget(max_model_calls=0),
                fence=current_fence(),
                parent_path=(),
            )
        self.assertEqual(registry.calls, [])

    def test_core_bridge_fences_late_output_after_cancellation(self):
        state = {"cancelled": False}
        handle = SimpleNamespace(expert_id="zara:expert/lisp", workspace="project")
        registry = RecordingCoreRegistry(
            result=core_result(),
            after_invoke=lambda: state.__setitem__("cancelled", True),
        )
        invoker = CoreLispFamilyCompositionInvoker(
            registry,
            activation_for=lambda _expert_id, _fence: handle,
            limits_factory=CoreLimits,
        )
        fence = InvocationFence(
            workspace_id="project",
            workspace_generation=4,
            is_cancelled=lambda: state["cancelled"],
            is_current_generation=lambda workspace, generation: (
                workspace == "project" and generation == 4
            ),
        )

        with self.assertRaisesRegex(CompositionError, "cancelled"):
            invoker(
                "zara:expert/lisp",
                "structural.check",
                {"arguments": ["(ok)"]},
                budget=SharedSymbolicBudget(max_model_calls=0),
                fence=fence,
                parent_path=(),
            )
        self.assertEqual(len(registry.calls), 1)

    def test_core_bridge_rejects_nonzero_model_ledger(self):
        handle = SimpleNamespace(expert_id="zara:expert/lisp", workspace="project")
        registry = RecordingCoreRegistry(result=core_result(model_calls=1))
        invoker = CoreLispFamilyCompositionInvoker(
            registry,
            activation_for=lambda _expert_id, _fence: handle,
            limits_factory=CoreLimits,
        )

        with self.assertRaisesRegex(CompositionError, "model use"):
            invoker(
                "zara:expert/lisp",
                "structural.check",
                {"arguments": ["(ok)"]},
                budget=SharedSymbolicBudget(max_model_calls=0),
                fence=current_fence(),
                parent_path=(),
            )
        self.assertEqual(len(registry.calls), 1)


if __name__ == "__main__":
    unittest.main()
