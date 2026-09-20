from __future__ import annotations

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
ZARA_CURRENT_CORE_ROOT = os.environ.get("ZARA_CURRENT_CORE_ROOT")
EXPECTED_DOTFILES_COMMIT = "423a00e4a93fbea8d191502b29b1d6ab0e1333fd"
EXPECTED_ZARA_CORE_COMMIT = "3c2f6ffe892fb5e39e395fa94fe5329f195d5923"
ZARA_EXPERT_LIB = REPO_ROOT / "plugins" / "zara-expert" / "lib"
LANGUAGES = ("javascript", "typescript", "java", "kotlin")
EXPERT_IDS = tuple(f"zara:expert/{language}" for language in LANGUAGES)
WORKSPACE_ID = "workspace:js-ts-java-kotlin-composition"
WORKSPACE_GENERATION = 23

if ZARA_CURRENT_CORE_ROOT:
    sys.path.insert(0, str(Path(ZARA_CURRENT_CORE_ROOT).resolve()))
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

if ZARA_CURRENT_CORE_ROOT:
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


@unittest.skipUnless(
    DOTFILES_ROOT and ZARA_CURRENT_CORE_ROOT,
    "exact Dotfiles and current Zara Core checkouts not provided",
)
class JsTsJavaKotlinCompositionFencesE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        cls.zara_core_root = Path(ZARA_CURRENT_CORE_ROOT).resolve()
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for composition fence E2E")
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
            for language in LANGUAGES
        }
        for source_files in cls.sources.values():
            for source in source_files:
                if not source.is_file():
                    raise AssertionError(f"missing canonical expert source: {source}")
        validate_language_source_contracts(cls.sources)

    @staticmethod
    def _source_payloads() -> dict[str, dict[str, str]]:
        return {
            "zara:expert/javascript": {
                "source": "export const answer = 42;",
                "source_generation": "generation-javascript",
            },
            "zara:expert/typescript": {
                "source": "export const answer: number = 42;",
                "source_generation": "generation-typescript",
            },
            "zara:expert/java": {
                "source": "public final class Answer { static final int VALUE = 42; }",
                "source_generation": "generation-java",
            },
            "zara:expert/kotlin": {
                "source": "object Answer { const val VALUE: Int = 42 }",
                "source_generation": "generation-kotlin",
            },
        }

    @staticmethod
    def _fence(
        *,
        cancelled: callable = lambda: False,
        current: callable = lambda workspace, generation: (
            workspace == WORKSPACE_ID and generation == WORKSPACE_GENERATION
        ),
    ) -> InvocationFence:
        return InvocationFence(
            workspace_id=WORKSPACE_ID,
            workspace_generation=WORKSPACE_GENERATION,
            is_cancelled=cancelled,
            is_current_generation=current,
        )

    def _core_composer(self) -> tuple[Any, CoreLanguageFamilyCompositionInvoker]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        host = ExpertHost(
            SwiplBackend(),
            state_root=Path(temporary.name) / "zara-expert-state",
        )
        registered = register_language_family(host, self.sources)
        self.assertEqual(registered, frozenset(LANGUAGES))
        published = {item["expert_id"]: item for item in descriptors(registered)}

        registry = ExpertRegistry(engines=("swipl",))
        handles: dict[str, Any] = {}
        for expert_id in EXPERT_IDS:
            registration = registry.register(
                ExpertDescriptor.from_wire(published[expert_id]),
                make_language_expert_handler(host, expert_id),
            )
            self.assertEqual(registration["expert_id"], expert_id)

        for expert_id in EXPERT_IDS:
            handle, receipt = registry.activate(
                "expert-builder-4",
                WORKSPACE_ID,
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

    def test_four_real_language_experts_share_one_zero_model_budget_and_evidence_tree(self) -> None:
        registry, core_invoker = self._core_composer()
        payloads = self._source_payloads()
        chain = {
            "zara:expert/javascript": "zara:expert/typescript",
            "zara:expert/typescript": "zara:expert/java",
            "zara:expert/java": "zara:expert/kotlin",
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
            child_id = chain.get(expert_id)
            if child_id is None:
                return result
            return replace(
                result,
                delegations=(
                    DelegationRequest(
                        expert_id=child_id,
                        operation="inspect",
                        input=payloads[child_id],
                        reason=f"trusted fixture composes {expert_id} evidence into {child_id}",
                    ),
                ),
            )

        composer = MetaExpertComposer(chained_invoker)
        budget = SharedSymbolicBudget(
            max_invocations=4,
            max_depth=3,
            max_evidence=64,
            max_model_calls=0,
        )
        root = composer.invoke(
            "zara:expert/javascript",
            "inspect",
            payloads["zara:expert/javascript"],
            budget=budget,
            fence=self._fence(),
        )

        nodes = [root]
        while nodes[-1].children:
            self.assertEqual(len(nodes[-1].children), 1)
            nodes.append(nodes[-1].children[0])

        self.assertEqual([node.expert_id for node in nodes], list(EXPERT_IDS))
        self.assertTrue(all(node.status == "succeeded" for node in nodes))
        self.assertTrue(all(node.evidence for node in nodes))
        self.assertTrue(all(node.explanation for node in nodes))
        self.assertEqual(nodes[-1].children, ())
        self.assertEqual(budget.invocations_used, 4)
        self.assertEqual(budget.evidence_used, sum(len(node.evidence) for node in nodes))
        self.assertEqual(budget.max_model_calls, 0)
        self.assertEqual(budget.model_calls_used, 0)
        self.assertEqual(len(registry.snapshot().invocation_ids), 4)

    def test_late_kotlin_result_is_fenced_before_evidence_commit(self) -> None:
        payloads = self._source_payloads()
        chain = {
            "zara:expert/javascript": "zara:expert/typescript",
            "zara:expert/typescript": "zara:expert/java",
            "zara:expert/java": "zara:expert/kotlin",
        }

        for invalidation in ("cancelled", "stale"):
            with self.subTest(invalidation=invalidation):
                registry, core_invoker = self._core_composer()
                state = {"cancelled": False, "current": True}
                observed: list[tuple[str, tuple[str, ...]]] = []
                fence = self._fence(
                    cancelled=lambda: state["cancelled"],
                    current=lambda workspace, generation: (
                        state["current"]
                        and workspace == WORKSPACE_ID
                        and generation == WORKSPACE_GENERATION
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
                    if expert_id == "zara:expert/kotlin":
                        if invalidation == "cancelled":
                            state["cancelled"] = True
                        else:
                            state["current"] = False
                        return result
                    child_id = chain[expert_id]
                    return replace(
                        result,
                        delegations=(
                            DelegationRequest(
                                expert_id=child_id,
                                operation="inspect",
                                input=payloads[child_id],
                                reason=f"trusted fixture composes {expert_id} evidence into {child_id}",
                            ),
                        ),
                    )

                composer = MetaExpertComposer(chained_invoker)
                budget = SharedSymbolicBudget(
                    max_invocations=4,
                    max_depth=3,
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
                        "zara:expert/javascript",
                        "inspect",
                        payloads["zara:expert/javascript"],
                        budget=budget,
                        fence=fence,
                    )

                self.assertEqual(
                    [expert_id for expert_id, _evidence in observed],
                    list(EXPERT_IDS),
                )
                self.assertTrue(all(evidence for _expert_id, evidence in observed))
                committed_parent_evidence = sum(
                    len(evidence) for _expert_id, evidence in observed[:-1]
                )
                all_dispatched_evidence = sum(
                    len(evidence) for _expert_id, evidence in observed
                )
                self.assertEqual(budget.invocations_used, 4)
                self.assertEqual(budget.evidence_used, committed_parent_evidence)
                self.assertLess(budget.evidence_used, all_dispatched_evidence)
                self.assertEqual(budget.max_model_calls, 0)
                self.assertEqual(budget.model_calls_used, 0)
                self.assertEqual(len(registry.snapshot().invocation_ids), 4)


if __name__ == "__main__":
    unittest.main()
