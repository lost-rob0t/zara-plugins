"""Persist typed Prolog/Python/Nim evidence through Zara symbolic conversation state."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests import test_prolog_python_nim_surface_parity_e2e as surface
from tests import test_prolog_python_nim_symbolic_conversation_e2e as conversation


DOTFILES_ROOT = os.environ.get("ZARA_DOTFILES_ROOT")
ZARA_CORE_ROOT = os.environ.get("ZARA_CORE_ROOT")
EXPECTED_DOTFILES_COMMIT = "3309c54ecb5f65c29374de6c60d2135a9ea2f94b"
EXPECTED_ZARA_CORE_COMMIT = "3cc472ca342868a0a3a3797e4e88371a6bbc390b"
_PROJECT_A = "workspace:prolog-python-nim:typed:A"
_PROJECT_B = "workspace:prolog-python-nim:typed:B"
_SYMBOLIC_RENDERER = "symbolic-dcg/v1"
_PROVIDER_CREDENTIALS = surface._PROVIDER_CREDENTIALS


def _checkout_head(root: Path, expected: str, label: str) -> None:
    result = surface._run("git", "rev-parse", "HEAD", cwd=root)
    if result.returncode != 0:
        raise AssertionError(f"cannot resolve {label} checkout: {result.stderr}")
    actual = result.stdout.strip()
    if actual != expected:
        raise AssertionError(
            f"{label} checkout must be exact: expected {expected}, got {actual}"
        )


def _android_twin(projection: Any) -> dict[str, Any]:
    return {
        "conversationId": projection.conversation_id,
        "projectionGeneration": projection.projection_generation,
        "runtimeGeneration": projection.runtime_generation,
        "turnId": projection.turn_id,
        "outcome": projection.outcome,
        "projectId": projection.project_id,
        "projectGeneration": projection.project_generation,
        "dialogueAct": projection.dialogue_act,
        "dialogueStateJson": surface._canonical_json(projection.dialogue_state),
        "expertEvidenceJson": surface._canonical_json(projection.expert_evidence),
        "rendererProvenance": projection.renderer_provenance,
        "providersEnabled": projection.providers_enabled,
        "maxModelCalls": projection.max_model_calls,
        "providerCalls": projection.provider_calls,
        "modelCalls": projection.model_calls,
    }


@unittest.skipUnless(
    DOTFILES_ROOT and ZARA_CORE_ROOT,
    "exact Dotfiles and Zara Core checkouts not provided",
)
class PrologPythonNimTypedPersistenceE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        cls.zara_core_root = Path(ZARA_CORE_ROOT).resolve()
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for typed persistence E2E")
        _checkout_head(cls.dotfiles_root, EXPECTED_DOTFILES_COMMIT, "Dotfiles producer")
        _checkout_head(cls.zara_core_root, EXPECTED_ZARA_CORE_COMMIT, "Zara Core")
        cls.sources = {
            language: [
                cls.dotfiles_root / ".zara" / "experts" / language / "kb" / "expert.pl"
            ]
            for language in ("prolog", "python", "nim")
        }
        for paths in cls.sources.values():
            for source in paths:
                if not source.is_file():
                    raise AssertionError(f"missing canonical expert source: {source}")
        cls.android_projection_source = (
            cls.zara_core_root
            / "android"
            / "app"
            / "src"
            / "main"
            / "java"
            / "ai"
            / "zara"
            / "app"
            / "history"
            / "SymbolicConversationProjection.kt"
        )
        if not cls.android_projection_source.is_file():
            raise AssertionError(
                f"missing Android projection contract: {cls.android_projection_source}"
            )

    def _surface_case(self) -> surface.PrologPythonNimSurfaceParityE2ETests:
        case = surface.PrologPythonNimSurfaceParityE2ETests(
            methodName="test_project_switch_fences_old_expert_context_on_both_surface_contracts"
        )
        case.dotfiles_root = self.dotfiles_root
        case.zara_core_root = self.zara_core_root
        case.sources = self.sources
        case.android_projection_source = self.android_projection_source
        return case

    def _typed_explanations(
        self,
        case: surface.PrologPythonNimSurfaceParityE2ETests,
        state_root: Path,
    ) -> dict[str, dict[str, Any]]:
        _published, handlers = case._runtime(state_root)
        explanations: dict[str, dict[str, Any]] = {}
        for index, expert_id in enumerate(
            ("zara:expert/prolog", "zara:expert/python", "zara:expert/nim"),
            start=1,
        ):
            outcome = handlers[expert_id](
                expert_operation="explain",
                decision_ref=f"decision:typed-persistence-{index}",
                source_generation=f"generation:typed-persistence-{index}",
            )
            self.assertEqual(outcome["verdict"], "succeeded")
            self.assertEqual(outcome["usage"], {"model_calls": 0})
            self.assertEqual(outcome["effect_receipts"], [])
            self.assertTrue(outcome["evidence_refs"])
            self.assertEqual(set(outcome["data"]), {"explanation"})
            explanation = outcome["data"]["explanation"]
            self.assertEqual(set(explanation), {"symbolic_terms", "trace"})
            self.assertTrue(explanation["symbolic_terms"])
            self.assertTrue(explanation["trace"])
            explanations[expert_id] = explanation
        return explanations

    def _assert_android_contract(self) -> None:
        source = self.android_projection_source.read_text(encoding="utf-8")
        required = (
            'val expertEvidenceJson: String = "[]"',
            'val providersEnabled: Boolean = true',
            'val maxModelCalls: Long = 1',
            'val providerCalls: Long = 0',
            'val modelCalls: Long = 0',
            '"project switch must advance projectGeneration"',
            '"provider policy widening rejected"',
            '"model-call budget widening rejected"',
        )
        for fragment in required:
            self.assertIn(fragment, source)

    def test_typed_evidence_survives_restart_then_is_fenced_on_project_switch(self) -> None:
        for name in _PROVIDER_CREDENTIALS:
            self.assertNotIn(name, os.environ)

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        case = self._surface_case()

        chain_evidence = case._real_chain(root / "expert-state-chain")
        explanations = self._typed_explanations(case, root / "expert-state-explain")
        self._assert_android_contract()

        typed_evidence: list[dict[str, Any]] = []
        for item in chain_evidence:
            entry = dict(item)
            entry["explanation"] = explanations[entry["expert_id"]]
            self.assertNotIn("result", entry)
            self.assertEqual(entry["model_calls"], 0)
            self.assertTrue(entry["evidence_refs"])
            typed_evidence.append(entry)
        typed_evidence.sort(key=lambda item: item["expert_id"])

        database_path = root / "conversation.db"
        database = surface.DatabaseManager(database_path)
        store = surface.ConversationStore(database)
        record = store.create_conversation(
            "Typed pure-symbolic language evidence",
            conversation_id="conversation:typed-prolog-python-nim",
        )
        store.save_message(
            case._message(
                record.id,
                1,
                "turn:typed-inspect",
                surface.MessageRole.USER,
                "Inspect this project with Prolog, Python, and Nim, then explain the result.",
            )
        )
        store.save_message(
            case._message(
                record.id,
                2,
                "turn:typed-inspect",
                surface.MessageRole.ASSISTANT,
                "The symbolic language inspection is complete.",
            )
        )
        project_a = store.save_symbolic_projection(
            surface.SymbolicConversationProjection(
                conversation_id=record.id,
                projection_generation=1,
                runtime_generation=1,
                turn_id="turn:typed-inspect",
                outcome="success",
                project_id=_PROJECT_A,
                project_generation=1,
                dialogue_act="expert.answer",
                dialogue_state={
                    "active_project": _PROJECT_A,
                    "selected_experts": [
                        "zara:expert/prolog",
                        "zara:expert/python",
                        "zara:expert/nim",
                    ],
                    "typed_explanation": True,
                },
                expert_evidence=typed_evidence,
                renderer_provenance=_SYMBOLIC_RENDERER,
                providers_enabled=False,
                max_model_calls=0,
                provider_calls=0,
                model_calls=0,
            ),
            expected_generation=0,
        )
        project_a.assert_pure_symbolic()
        database.close()

        reopened_database = surface.DatabaseManager(database_path)
        reopened = surface.ConversationStore(reopened_database)
        recovered_a = reopened.load_symbolic_projection(record.id)
        self.assertIsNotNone(recovered_a)
        assert recovered_a is not None
        recovered_a.assert_pure_symbolic()
        self.assertEqual(recovered_a.expert_evidence, typed_evidence)
        android_a = _android_twin(recovered_a)
        self.assertEqual(json.loads(android_a["expertEvidenceJson"]), typed_evidence)
        self.assertIs(android_a["providersEnabled"], False)
        self.assertEqual(android_a["maxModelCalls"], 0)
        self.assertEqual(android_a["providerCalls"], 0)
        self.assertEqual(android_a["modelCalls"], 0)

        prolog_entry = next(
            item
            for item in recovered_a.expert_evidence
            if item["expert_id"] == "zara:expert/prolog"
        )
        self.assertTrue(prolog_entry["explanation"]["symbolic_terms"])
        self.assertTrue(prolog_entry["explanation"]["trace"])
        dialogue_case = conversation.PrologPythonNimSymbolicConversationE2ETests(
            methodName="test_real_three_expert_chain_survives_restart_and_answers_why"
        )
        dialogue_case.zara_core_root = self.zara_core_root
        evidence_ref = prolog_entry["evidence_refs"][0]
        _answer, why = dialogue_case._run_symbolic_dialogue(evidence_ref)
        self.assertEqual(why, f"I answered from evidence {evidence_ref}.")

        project_b = reopened.save_symbolic_projection(
            surface.SymbolicConversationProjection(
                conversation_id=record.id,
                projection_generation=2,
                runtime_generation=2,
                turn_id="turn:project-switch",
                outcome="success",
                project_id=_PROJECT_B,
                project_generation=2,
                dialogue_act="clarify",
                dialogue_state={
                    "active_project": _PROJECT_B,
                    "previous_project_evidence": "fenced",
                },
                expert_evidence=[],
                renderer_provenance=_SYMBOLIC_RENDERER,
                providers_enabled=False,
                max_model_calls=0,
                provider_calls=0,
                model_calls=0,
            ),
            expected_generation=project_a.projection_generation,
        )
        project_b.assert_pure_symbolic()

        with self.assertRaisesRegex(RuntimeError, "project switch must advance"):
            reopened.save_symbolic_projection(
                surface.SymbolicConversationProjection(
                    conversation_id=record.id,
                    projection_generation=3,
                    runtime_generation=3,
                    turn_id="turn:stale-project-a",
                    outcome="success",
                    project_id=_PROJECT_A,
                    project_generation=1,
                    dialogue_act="expert.answer",
                    expert_evidence=typed_evidence,
                    renderer_provenance=_SYMBOLIC_RENDERER,
                    providers_enabled=False,
                    max_model_calls=0,
                    provider_calls=0,
                    model_calls=0,
                ),
                expected_generation=project_b.projection_generation,
            )

        current = reopened.load_symbolic_projection(record.id)
        self.assertIsNotNone(current)
        assert current is not None
        current.assert_pure_symbolic()
        self.assertEqual(current.project_id, _PROJECT_B)
        self.assertEqual(current.project_generation, 2)
        self.assertEqual(current.expert_evidence, [])
        android_b = _android_twin(current)
        self.assertEqual(json.loads(android_b["expertEvidenceJson"]), [])
        self.assertIs(android_b["providersEnabled"], False)
        self.assertEqual(android_b["maxModelCalls"], 0)
        self.assertEqual(android_b["providerCalls"], 0)
        self.assertEqual(android_b["modelCalls"], 0)
        reopened_database.close()


if __name__ == "__main__":
    unittest.main()
