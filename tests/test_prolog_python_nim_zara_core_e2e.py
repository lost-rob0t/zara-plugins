import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DOTFILES_ROOT = os.environ.get("ZARA_DOTFILES_ROOT")
ZARA_CORE_ROOT = os.environ.get("ZARA_CORE_ROOT")
EXPECTED_DOTFILES_COMMIT = "1b93e01f3482e49a853f651eb28c21eb1d9cad0e"
EXPECTED_ZARA_CORE_COMMIT = "fded1099e82f315b069676d1aadd66fe96aebccc"
ZARA_EXPERT_LIB = REPO_ROOT / "plugins" / "zara-expert" / "lib"

if ZARA_CORE_ROOT:
    sys.path.insert(0, str(Path(ZARA_CORE_ROOT).resolve()))
sys.path.insert(0, str(ZARA_EXPERT_LIB))

from zara_expert.backend import SwiplBackend
from zara_expert.composition import (
    CompositionError,
    DelegationRequest,
    InvocationFence,
    MetaExpertComposer,
    SharedSymbolicBudget,
)
from zara_expert.domain import ExpertHost
from zara_expert.language_composition import CoreLanguageFamilyCompositionInvoker
from zara_expert.language_family import descriptors, register_language_family
from zara_expert.language_handler import make_language_expert_handler
from zara_expert.language_source_contract import validate_language_source_contracts

if ZARA_CORE_ROOT:
    from zara.experts import ExpertDescriptor, ExpertLimits, ExpertRegistry, ExpertVerdict


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


@unittest.skipUnless(
    DOTFILES_ROOT and ZARA_CORE_ROOT,
    "exact Dotfiles and Zara Core checkouts not provided",
)
class PrologPythonNimZaraCoreE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        cls.zara_core_root = Path(ZARA_CORE_ROOT).resolve()
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for Zara Core expert E2E")
        _checkout_head(cls.dotfiles_root, EXPECTED_DOTFILES_COMMIT, "Dotfiles producer")
        _checkout_head(cls.zara_core_root, EXPECTED_ZARA_CORE_COMMIT, "Zara Core")
        cls.sources = {
            language: [
                cls.dotfiles_root
                / ".zara"
                / "experts"
                / language
                / "kb"
                / "expert.pl"
            ]
            for language in ("prolog", "python", "nim")
        }
        for paths in cls.sources.values():
            for source in paths:
                if not source.is_file():
                    raise AssertionError(f"missing canonical expert source: {source}")

    @staticmethod
    def _fence() -> InvocationFence:
        return InvocationFence(
            workspace_id="workspace:prolog-python-nim-e2e",
            workspace_generation=11,
            is_cancelled=lambda: False,
            is_current_generation=lambda workspace, generation: (
                workspace == "workspace:prolog-python-nim-e2e" and generation == 11
            ),
        )

    def _core_composer(self):
        validate_language_source_contracts(self.sources)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        host = ExpertHost(
            SwiplBackend(),
            state_root=Path(temporary.name) / "zara-expert-state",
        )
        registered = register_language_family(host, self.sources)
        self.assertEqual(registered, frozenset({"prolog", "python", "nim"}))
        published = {item["expert_id"]: item for item in descriptors(registered)}

        registry = ExpertRegistry(engines=("swipl",))
        for expert_id in (
            "zara:expert/prolog",
            "zara:expert/python",
            "zara:expert/nim",
        ):
            descriptor = ExpertDescriptor.from_wire(published[expert_id])
            registration = registry.register(
                descriptor,
                make_language_expert_handler(host, expert_id),
            )
            self.assertEqual(registration["expert_id"], expert_id)

        handles = {}
        for expert_id in (
            "zara:expert/prolog",
            "zara:expert/python",
            "zara:expert/nim",
        ):
            handle, receipt = registry.activate(
                "expert-builder-3",
                "workspace:prolog-python-nim-e2e",
                expert_id,
                expected_registry_generation=registry.generation,
                expected_runtime_generation=registry.runtime_generation,
            )
            self.assertEqual(receipt["state"], "active")
            handles[expert_id] = handle

        invoker = CoreLanguageFamilyCompositionInvoker(
            registry,
            activation_for=lambda expert_id, _fence: handles[expert_id],
            limits_factory=ExpertLimits,
        )
        return registry, invoker

    def test_real_brains_cross_core_with_one_exact_zero_model_budget(self) -> None:
        registry, invoker = self._core_composer()
        composer = MetaExpertComposer(invoker)
        budget = SharedSymbolicBudget(
            max_invocations=3,
            max_evidence=64,
            max_model_calls=0,
        )
        fence = self._fence()
        cases = (
            ("zara:expert/prolog", "fact(a)."),
            ("zara:expert/python", "def answer():\n    return 42\n"),
            ("zara:expert/nim", "proc answer(): int = 42\n"),
        )

        evidence_count = 0
        for index, (expert_id, source) in enumerate(cases, start=1):
            with self.subTest(expert_id=expert_id):
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
                self.assertTrue(node.evidence)
                self.assertEqual(node.children, ())
                evidence_count += len(node.evidence)

        self.assertEqual(budget.invocations_used, 3)
        self.assertEqual(budget.evidence_used, evidence_count)
        self.assertEqual(budget.max_model_calls, 0)
        self.assertEqual(budget.model_calls_used, 0)
        self.assertEqual(len(registry.snapshot().invocation_ids), 3)

    def test_nested_prolog_python_nim_delegation_uses_same_budget_and_core_path(self) -> None:
        _registry, core_invoker = self._core_composer()
        sources = {
            "zara:expert/prolog": {
                "source": "fact(a).",
                "source_generation": "generation-prolog",
            },
            "zara:expert/python": {
                "source": "def answer():\n    return 42\n",
                "source_generation": "generation-python",
            },
            "zara:expert/nim": {
                "source": "proc answer(): int = 42\n",
                "source_generation": "generation-nim",
            },
        }

        def chained_invoker(
            expert_id: str,
            operation: str,
            input_data: dict[str, Any],
            *,
            budget: SharedSymbolicBudget,
            fence: InvocationFence,
            parent_path: tuple[str, ...],
        ):
            result = core_invoker(
                expert_id,
                operation,
                input_data,
                budget=budget,
                fence=fence,
                parent_path=parent_path,
            )
            if expert_id == "zara:expert/prolog":
                return replace(
                    result,
                    delegations=(
                        DelegationRequest(
                            expert_id="zara:expert/python",
                            operation="inspect",
                            input=sources["zara:expert/python"],
                            reason="trusted fixture delegates Prolog evidence to Python",
                        ),
                    ),
                )
            if expert_id == "zara:expert/python":
                return replace(
                    result,
                    delegations=(
                        DelegationRequest(
                            expert_id="zara:expert/nim",
                            operation="inspect",
                            input=sources["zara:expert/nim"],
                            reason="trusted fixture delegates Python evidence to Nim",
                        ),
                    ),
                )
            return result

        composer = MetaExpertComposer(chained_invoker)
        budget = SharedSymbolicBudget(
            max_invocations=3,
            max_depth=2,
            max_evidence=64,
            max_model_calls=0,
        )
        root = composer.invoke(
            "zara:expert/prolog",
            "inspect",
            sources["zara:expert/prolog"],
            budget=budget,
            fence=self._fence(),
        )

        self.assertEqual(root.expert_id, "zara:expert/prolog")
        self.assertEqual(len(root.children), 1)
        python = root.children[0]
        self.assertEqual(python.expert_id, "zara:expert/python")
        self.assertEqual(len(python.children), 1)
        nim = python.children[0]
        self.assertEqual(nim.expert_id, "zara:expert/nim")
        self.assertEqual(nim.children, ())
        self.assertEqual(
            (root.status, python.status, nim.status),
            ("succeeded", "succeeded", "succeeded"),
        )
        evidence_count = len(root.evidence) + len(python.evidence) + len(nim.evidence)
        self.assertEqual(budget.invocations_used, 3)
        self.assertEqual(budget.evidence_used, evidence_count)
        self.assertEqual(budget.max_model_calls, 0)
        self.assertEqual(budget.model_calls_used, 0)

    def test_nested_late_nim_output_is_fenced_before_evidence_tree_commit(self) -> None:
        sources = {
            "zara:expert/prolog": {
                "source": "fact(a).",
                "source_generation": "generation-prolog",
            },
            "zara:expert/python": {
                "source": "def answer():\n    return 42\n",
                "source_generation": "generation-python",
            },
            "zara:expert/nim": {
                "source": "proc answer(): int = 42\n",
                "source_generation": "generation-nim",
            },
        }

        for invalidation in ("cancelled", "stale"):
            with self.subTest(invalidation=invalidation):
                registry, core_invoker = self._core_composer()
                state = {"cancelled": False, "current": True}
                observed: list[tuple[str, tuple[str, ...]]] = []
                fence = InvocationFence(
                    workspace_id="workspace:prolog-python-nim-e2e",
                    workspace_generation=11,
                    is_cancelled=lambda: state["cancelled"],
                    is_current_generation=lambda workspace, generation: (
                        state["current"]
                        and workspace == "workspace:prolog-python-nim-e2e"
                        and generation == 11
                    ),
                )

                def chained_invoker(
                    expert_id: str,
                    operation: str,
                    input_data: dict[str, Any],
                    *,
                    budget: SharedSymbolicBudget,
                    fence: InvocationFence,
                    parent_path: tuple[str, ...],
                ):
                    result = core_invoker(
                        expert_id,
                        operation,
                        input_data,
                        budget=budget,
                        fence=fence,
                        parent_path=parent_path,
                    )
                    observed.append((expert_id, tuple(result.evidence)))
                    if expert_id == "zara:expert/nim":
                        if invalidation == "cancelled":
                            state["cancelled"] = True
                        else:
                            state["current"] = False
                        return result
                    if expert_id == "zara:expert/prolog":
                        return replace(
                            result,
                            delegations=(
                                DelegationRequest(
                                    expert_id="zara:expert/python",
                                    operation="inspect",
                                    input=sources["zara:expert/python"],
                                    reason="trusted fixture delegates Prolog evidence to Python",
                                ),
                            ),
                        )
                    return replace(
                        result,
                        delegations=(
                            DelegationRequest(
                                expert_id="zara:expert/nim",
                                operation="inspect",
                                input=sources["zara:expert/nim"],
                                reason="trusted fixture delegates Python evidence to Nim",
                            ),
                        ),
                    )

                composer = MetaExpertComposer(chained_invoker)
                budget = SharedSymbolicBudget(
                    max_invocations=3,
                    max_depth=2,
                    max_evidence=64,
                    max_model_calls=0,
                )
                expected_error = (
                    "expert invocation cancelled"
                    if invalidation == "cancelled"
                    else "stale workspace generation"
                )
                with self.assertRaisesRegex(CompositionError, expected_error):
                    composer.invoke(
                        "zara:expert/prolog",
                        "inspect",
                        sources["zara:expert/prolog"],
                        budget=budget,
                        fence=fence,
                    )

                self.assertEqual(
                    [expert_id for expert_id, _evidence in observed],
                    [
                        "zara:expert/prolog",
                        "zara:expert/python",
                        "zara:expert/nim",
                    ],
                )
                self.assertTrue(all(evidence for _expert_id, evidence in observed))
                self.assertEqual(len(registry.snapshot().invocation_ids), 3)
                self.assertEqual(budget.invocations_used, 3)
                committed_parent_evidence = sum(
                    len(evidence) for _expert_id, evidence in observed[:-1]
                )
                all_dispatched_evidence = sum(
                    len(evidence) for _expert_id, evidence in observed
                )
                self.assertEqual(budget.evidence_used, committed_parent_evidence)
                self.assertLess(budget.evidence_used, all_dispatched_evidence)
                self.assertEqual(budget.max_model_calls, 0)
                self.assertEqual(budget.model_calls_used, 0)

    def test_repair_apply_is_blocked_without_effect_success(self) -> None:
        _registry, invoker = self._core_composer()
        composer = MetaExpertComposer(invoker)
        budget = SharedSymbolicBudget(max_invocations=1, max_model_calls=0)
        node = composer.invoke(
            "zara:expert/prolog",
            "repair.apply",
            {
                "repair": {"kind": "preview-only"},
                "expected_preimage": "fact(a).",
                "source_generation": "generation-repair",
            },
            budget=budget,
            fence=self._fence(),
        )

        self.assertEqual(node.status, "blocked")
        self.assertEqual(node.data["reason"], "canonical-typed-edit-required")
        self.assertEqual(node.evidence, ())
        self.assertEqual(budget.invocations_used, 1)
        self.assertEqual(budget.model_calls_used, 0)


if __name__ == "__main__":
    unittest.main()
