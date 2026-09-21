import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOTFILES_ROOT = os.environ.get("ZARA_DOTFILES_ROOT")
ZARA_CORE_ROOT = os.environ.get("ZARA_CORE_ROOT")
EXPECTED_DOTFILES_COMMIT = "fe8f7fa3c42803e0e505dcb6f7e4600d27649d9e"
EXPECTED_ZARA_CORE_COMMIT = "8177460982f94a5a60cf454c2fd4f9beae867a95"
ZARA_EXPERT_LIB = REPO_ROOT / "plugins" / "zara-expert" / "lib"

if ZARA_CORE_ROOT:
    sys.path.insert(0, str(Path(ZARA_CORE_ROOT).resolve()))
sys.path.insert(0, str(ZARA_EXPERT_LIB))

from zara_expert.backend import SwiplBackend
from zara_expert.composition import InvocationFence, MetaExpertComposer, SharedSymbolicBudget
from zara_expert.domain import ExpertHost
from zara_expert.lisp_composition import CoreLispFamilyCompositionInvoker
from zara_expert.lisp_family import descriptors, make_lisp_expert_handler, register_lisp_family
from zara_expert.lisp_source_contract import validate_lisp_source_contracts

if ZARA_CORE_ROOT:
    from zara.experts import ExpertDescriptor, ExpertLimits, ExpertRegistry


def _run(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _checkout_head(root: Path, expected: str, label: str) -> None:
    result = _run("git", "rev-parse", "HEAD", cwd=root)
    if result.returncode != 0:
        raise AssertionError(f"cannot resolve {label} checkout: {result.stderr}")
    actual = result.stdout.strip()
    if actual != expected:
        raise AssertionError(
            f"{label} checkout must be exact: expected {expected}, got {actual}"
        )


class _BlockAfterRealLispBackend(SwiplBackend):
    """Hold one real generic-Lisp repair result before Core can commit it."""

    def __init__(self) -> None:
        super().__init__()
        self.completed = threading.Event()
        self.release = threading.Event()
        self.preview_calls = 0

    def run(self, request):
        result = super().run(request)
        capability = request.get("capability")
        if (
            getattr(capability, "namespace", None) == "lisp"
            and getattr(capability, "predicate", None) == "preview_repair"
        ):
            self.preview_calls += 1
            self.completed.set()
            if not self.release.wait(timeout=5.0):
                raise AssertionError("real Lisp repair backend was not released")
        return result


@unittest.skipUnless(
    DOTFILES_ROOT and ZARA_CORE_ROOT,
    "exact Dotfiles and Zara Core checkouts not provided",
)
class LispCurrentCoreDelegationE2ETests(unittest.TestCase):
    WORKSPACE = "workspace:lisp-current-core"

    @classmethod
    def setUpClass(cls) -> None:
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        cls.zara_core_root = Path(ZARA_CORE_ROOT).resolve()
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for Lisp current-Core E2E")
        _checkout_head(cls.dotfiles_root, EXPECTED_DOTFILES_COMMIT, "Dotfiles producer")
        _checkout_head(cls.zara_core_root, EXPECTED_ZARA_CORE_COMMIT, "Zara Core")
        cls.sources = {
            key: [
                cls.dotfiles_root
                / ".zara"
                / "experts"
                / key
                / "kb"
                / "expert.pl"
            ]
            for key in ("lisp", "common-lisp", "emacs-lisp")
        }
        for paths in cls.sources.values():
            for source in paths:
                if not source.is_file():
                    raise AssertionError(f"missing canonical Lisp source: {source}")
        validate_lisp_source_contracts(cls.sources)

    def _runtime(self, *, backend=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        host = ExpertHost(
            backend if backend is not None else SwiplBackend(),
            state_root=Path(temporary.name) / "zara-expert-state",
            query_timeout_seconds=5.0,
        )
        registered = register_lisp_family(host, self.sources)
        self.assertEqual(
            registered,
            frozenset({"lisp", "common-lisp", "emacs-lisp"}),
        )
        published = {item["expert_id"]: item for item in descriptors(registered)}
        registry = ExpertRegistry(engines=("swipl",))
        for expert_id in (
            "zara:expert/lisp",
            "zara:expert/common-lisp",
            "zara:expert/emacs-lisp",
        ):
            registry.register(
                ExpertDescriptor.from_wire(published[expert_id]),
                make_lisp_expert_handler(host, expert_id),
            )
        handles = {}
        for expert_id in published:
            if expert_id not in {
                "zara:expert/lisp",
                "zara:expert/common-lisp",
                "zara:expert/emacs-lisp",
            }:
                continue
            handle, receipt = registry.activate(
                "expert-builder-1",
                self.WORKSPACE,
                expert_id,
                expected_registry_generation=registry.generation,
                expected_runtime_generation=registry.runtime_generation,
            )
            self.assertEqual(receipt["state"], "active")
            handles[expert_id] = handle
        return registry, handles

    def _fence(self) -> InvocationFence:
        return InvocationFence(
            workspace_id=self.WORKSPACE,
            workspace_generation=1,
            is_cancelled=lambda: False,
            is_current_generation=lambda workspace, generation: (
                workspace == self.WORKSPACE and generation == 1
            ),
        )

    def _composer(self, registry, handles):
        def activation_for(expert_id, fence):
            self.assertEqual(fence.workspace_id, self.WORKSPACE)
            return handles[expert_id]

        return MetaExpertComposer(
            CoreLispFamilyCompositionInvoker(
                registry,
                activation_for=activation_for,
                limits_factory=ExpertLimits,
            )
        )

    def test_common_and_emacs_lisp_preview_delegate_to_real_lisp_under_one_zero_model_budget(self) -> None:
        registry, handles = self._runtime()
        composer = self._composer(registry, handles)

        cases = (
            (
                "zara:expert/common-lisp",
                "(defun demo (x) (list x",
            ),
            (
                "zara:expert/emacs-lisp",
                '(defun demo (x) (list x ?\\()',
            ),
        )
        for expert_id, source in cases:
            with self.subTest(expert=expert_id):
                budget = SharedSymbolicBudget(
                    max_invocations=2,
                    max_depth=1,
                    max_model_calls=0,
                )
                tree = composer.invoke(
                    expert_id,
                    "repair.preview",
                    {
                        "arguments": [
                            source,
                            "diagnostic:lisp:missing-close",
                        ]
                    },
                    budget=budget,
                    fence=self._fence(),
                )

                self.assertEqual(tree.status, "unknown")
                self.assertEqual(tree.data["delegated_to"], "zara:expert/lisp")
                self.assertEqual(len(tree.children), 1)
                child = tree.children[0]
                self.assertEqual(child.expert_id, "zara:expert/lisp")
                self.assertEqual(child.operation, "repair.preview")
                self.assertEqual(child.status, "succeeded")
                rendered = " ".join(child.data["result"]["results"])
                self.assertIn("status(proposed)", rendered)
                self.assertIn("fresh_dialect_reader_postcondition", rendered)
                self.assertTrue(child.evidence)
                self.assertEqual(budget.invocations_used, 2)
                self.assertEqual(budget.model_calls_used, 0)

        self.assertEqual(len(registry.snapshot().invocation_ids), 2)

    def test_real_dialect_verification_remains_symbolic_and_requires_fresh_reader_postcondition(self) -> None:
        registry, handles = self._runtime()
        composer = self._composer(registry, handles)

        cases = (
            (
                "zara:expert/common-lisp",
                "sbcl_fresh_reader_and_compile_evidence",
            ),
            (
                "zara:expert/emacs-lisp",
                "emacs_fresh_reader_and_byte_compile_evidence",
            ),
        )
        for expert_id, postcondition in cases:
            with self.subTest(expert=expert_id):
                budget = SharedSymbolicBudget(max_model_calls=0)
                tree = composer.invoke(
                    expert_id,
                    "repair.verify",
                    {
                        "arguments": [
                            "(defun demo (x) (list x",
                            "(defun demo (x) (list x))",
                        ]
                    },
                    budget=budget,
                    fence=self._fence(),
                )
                self.assertEqual(tree.status, "blocked")
                rendered = " ".join(tree.data["result"]["results"])
                self.assertIn("verified(false)", rendered)
                self.assertIn(postcondition, rendered)
                self.assertTrue(tree.evidence)
                self.assertEqual(budget.model_calls_used, 0)

    def test_repair_apply_stays_blocked_inside_core_without_effect_receipts(self) -> None:
        registry, handles = self._runtime()
        composer = self._composer(registry, handles)
        budget = SharedSymbolicBudget(max_model_calls=0)

        tree = composer.invoke(
            "zara:expert/common-lisp",
            "repair.apply",
            {
                "repair": {"kind": "insert", "offset": 24, "text": ")"},
                "expected_preimage": "sha256:fixture",
                "source_generation": "buffer:1",
            },
            budget=budget,
            fence=self._fence(),
        )

        self.assertEqual(tree.status, "blocked")
        self.assertEqual(tree.data["reason"], "canonical-typed-edit-required")
        self.assertEqual(tree.evidence, ())
        self.assertEqual(budget.model_calls_used, 0)
        self.assertEqual(len(registry.snapshot().invocation_ids), 1)

    def test_core_cancellation_fences_real_delegated_lisp_output_before_commit(self) -> None:
        backend = _BlockAfterRealLispBackend()
        registry, handles = self._runtime(backend=backend)
        composer = self._composer(registry, handles)
        budget = SharedSymbolicBudget(
            max_invocations=2,
            max_depth=1,
            max_model_calls=0,
        )
        outcome = {}

        def invoke_repair() -> None:
            try:
                outcome["result"] = composer.invoke(
                    "zara:expert/common-lisp",
                    "repair.preview",
                    {
                        "arguments": [
                            "(defun demo (x) (list x",
                            "diagnostic:lisp:missing-close",
                        ]
                    },
                    budget=budget,
                    fence=self._fence(),
                )
            except BaseException as exc:  # pragma: no cover - failure surfaced below
                outcome["error"] = exc

        worker = threading.Thread(target=invoke_repair, daemon=True)
        worker.start()
        self.assertTrue(
            backend.completed.wait(timeout=5.0),
            "real Lisp backend did not complete before cancellation",
        )
        self.assertEqual(backend.preview_calls, 1)

        invocation_ids = registry.snapshot().invocation_ids
        self.assertEqual(len(invocation_ids), 1)
        child_invocation_id = invocation_ids[0]
        before = registry.explain(child_invocation_id)
        self.assertEqual(before["expert_id"], "zara:expert/lisp")

        receipt = registry.cancel(child_invocation_id)
        self.assertIs(receipt["cancelled"], True)
        self.assertIs(receipt["committed"], False)

        backend.release.set()
        worker.join(timeout=5.0)
        self.assertFalse(worker.is_alive(), "cancelled Lisp delegation did not terminate")
        self.assertNotIn("error", outcome)

        tree = outcome["result"]
        self.assertEqual(tree.status, "unknown")
        self.assertEqual(len(tree.children), 1)
        child = tree.children[0]
        self.assertEqual(child.expert_id, "zara:expert/lisp")
        self.assertEqual(child.status, "cancelled")
        self.assertEqual(child.evidence, ())
        self.assertEqual(child.data, {})
        self.assertEqual(budget.invocations_used, 2)
        self.assertEqual(budget.model_calls_used, 0)

        trace = registry.explain(child_invocation_id)
        self.assertEqual(trace["verdict"], "cancelled")
        self.assertEqual(trace["evidence_refs"], [])
        self.assertEqual(trace.get("effect_receipts", []), [])
        self.assertIs(type(trace["usage"]["model_calls"]), int)
        self.assertEqual(trace["usage"]["model_calls"], 0)

        fresh_budget = SharedSymbolicBudget(max_model_calls=0)
        fresh = composer.invoke(
            "zara:expert/lisp",
            "structural.check",
            {"arguments": ["(fresh)"]},
            budget=fresh_budget,
            fence=self._fence(),
        )
        self.assertEqual(fresh.status, "succeeded")
        self.assertTrue(fresh.evidence)
        self.assertEqual(fresh_budget.model_calls_used, 0)


if __name__ == "__main__":
    unittest.main()
