"""Gate real Prolog/Python/Nim evidence across clarification and restart.

This acceptance slice deliberately reuses Zara Core's canonical pure-symbolic
runtime, ConversationStore projection owner, and zara-expert adapters.  It does
not add a conversation store, renderer, expert registry, provider runtime, or
permission path.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests import test_prolog_python_nim_surface_parity_e2e as surface


DOTFILES_ROOT = os.environ.get("ZARA_DOTFILES_ROOT")
ZARA_CORE_ROOT = os.environ.get("ZARA_CORE_ROOT")
EXPECTED_DOTFILES_COMMIT = "3309c54ecb5f65c29374de6c60d2135a9ea2f94b"
EXPECTED_ZARA_CORE_COMMIT = "dcb39985b96ba9e3451c2f1cca99c7aa049c2800"
_PROJECT = "workspace:prolog-python-nim:clarification-continuity"
_SYMBOLIC_RENDERER = "symbolic-dcg/v1"
_PROVIDER_CREDENTIALS = surface._PROVIDER_CREDENTIALS

if ZARA_CORE_ROOT:
    from zara.database import DatabaseManager
    from zara.desktop.conversation import ConversationStore, SymbolicConversationProjection
    from zara.desktop.conversation.models import MessageRole
    from zara.desktop.conversation.symbolic_runtime import PureSymbolicProjectionAdapter
    from zara.runtime.pure_symbolic_backend import PureSymbolicRuntimeBackend


@unittest.skipUnless(
    DOTFILES_ROOT and ZARA_CORE_ROOT,
    "exact Dotfiles and Zara Core checkouts not provided",
)
class PrologPythonNimClarificationContinuityE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        cls.zara_core_root = Path(ZARA_CORE_ROOT).resolve()
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for clarification continuity E2E")
        surface._checkout_head(
            cls.dotfiles_root,
            EXPECTED_DOTFILES_COMMIT,
            "Dotfiles producer",
        )
        surface._checkout_head(
            cls.zara_core_root,
            EXPECTED_ZARA_CORE_COMMIT,
            "Zara Core",
        )
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

    def _real_expert_evidence(self, state_root: Path) -> list[dict[str, Any]]:
        return self._surface_case()._real_chain(state_root)

    async def _symbolic_turn(
        self,
        store: Any,
        conversation_id: str,
        text: str,
        turn_id: str,
    ) -> Any:
        backend = PureSymbolicRuntimeBackend(
            projection_adapter=PureSymbolicProjectionAdapter(store)
        )
        await backend.start()
        try:
            result = await backend.submit_turn(
                text,
                turn_id=turn_id,
                conversation_id=conversation_id,
            )
            self.assertEqual(result.metadata["route"], "pure_symbolic")
            self.assertIs(result.metadata["providers_enabled"], False)
            for key in (
                "max_provider_calls",
                "max_model_calls",
                "provider_calls",
                "model_calls",
            ):
                self.assertIs(type(result.metadata[key]), int)
                self.assertEqual(result.metadata[key], 0)
            backend.commit_turn_result(
                result,
                turn_id=turn_id,
                conversation_id=conversation_id,
            )
            return result
        finally:
            await backend.stop()

    def _assert_android_zero_model_contract(self) -> None:
        source = self.android_projection_source.read_text(encoding="utf-8")
        for fragment in (
            'check(!providersEnabled)',
            'check(maxModelCalls == 0L)',
            'check(providerCalls == 0L && modelCalls == 0L)',
            '"desktop_symbolic_projections"',
        ):
            self.assertIn(fragment, source)

    def test_real_expert_evidence_survives_clarification_and_backend_restart(self) -> None:
        for name in _PROVIDER_CREDENTIALS:
            self.assertNotIn(name, os.environ)

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        expert_evidence = self._real_expert_evidence(root / "expert-state")
        self.assertEqual(
            {item["expert_id"] for item in expert_evidence},
            {
                "zara:expert/prolog",
                "zara:expert/python",
                "zara:expert/nim",
            },
        )
        for item in expert_evidence:
            self.assertEqual(item["verdict"], "succeeded")
            self.assertTrue(item["evidence_refs"])
            self.assertIs(type(item["model_calls"]), int)
            self.assertEqual(item["model_calls"], 0)
        self._assert_android_zero_model_contract()

        database_path = root / "conversation.db"
        database = DatabaseManager(database_path)
        store = ConversationStore(database)
        conversation = store.create_conversation(
            "Prolog Python Nim clarification continuity",
            conversation_id="conversation:prolog-python-nim:clarification-continuity",
        )
        case = self._surface_case()
        store.save_message(
            case._message(
                conversation.id,
                1,
                "turn:expert-inspect",
                MessageRole.USER,
                "Inspect this project with Prolog, Python, and Nim.",
            )
        )
        store.save_message(
            case._message(
                conversation.id,
                2,
                "turn:expert-inspect",
                MessageRole.ASSISTANT,
                "The symbolic language inspection is ready.",
            )
        )
        initial = store.save_symbolic_projection(
            SymbolicConversationProjection(
                conversation_id=conversation.id,
                projection_generation=1,
                runtime_generation=1,
                turn_id="turn:expert-inspect",
                outcome="success",
                project_id=_PROJECT,
                project_generation=1,
                dialogue_act="expert.answer",
                dialogue_state={
                    "active_project": _PROJECT,
                    "selected_experts": [
                        "zara:expert/prolog",
                        "zara:expert/python",
                        "zara:expert/nim",
                    ],
                },
                expert_evidence=expert_evidence,
                renderer_provenance=_SYMBOLIC_RENDERER,
                providers_enabled=False,
                max_model_calls=0,
                provider_calls=0,
                model_calls=0,
            ),
            expected_generation=0,
        )
        initial.assert_pure_symbolic()

        store.save_message(
            case._message(
                conversation.id,
                3,
                "turn:clarify-duration",
                MessageRole.USER,
                "timer",
            )
        )
        clarify = asyncio.run(
            self._symbolic_turn(
                store,
                conversation.id,
                "timer",
                "turn:clarify-duration",
            )
        )
        self.assertEqual(clarify.response, "How long should I set the timer for?")
        store.save_message(
            case._message(
                conversation.id,
                4,
                "turn:clarify-duration",
                MessageRole.ASSISTANT,
                clarify.response,
            )
        )

        clarified = store.load_symbolic_projection(conversation.id)
        self.assertIsNotNone(clarified)
        assert clarified is not None
        clarified.assert_pure_symbolic()
        self.assertEqual(clarified.projection_generation, 2)
        self.assertEqual(clarified.runtime_generation, 2)
        self.assertEqual(clarified.project_id, _PROJECT)
        self.assertEqual(clarified.project_generation, 1)
        self.assertEqual(clarified.dialogue_act, "clarify")
        self.assertEqual(clarified.expert_evidence, expert_evidence)
        self.assertIn("partial_frame", clarified.dialogue_state["prolog_context_term"])
        self.assertEqual(
            clarified.unresolved_questions,
            [
                {
                    "id": "turn:turn:clarify-duration:clarification",
                    "text": "How long should I set the timer for?",
                    "source": "symbolic_dialogue",
                }
            ],
        )
        self.assertIs(clarified.providers_enabled, False)
        self.assertEqual(clarified.max_model_calls, 0)
        self.assertEqual(clarified.provider_calls, 0)
        self.assertEqual(clarified.model_calls, 0)
        database.close()

        # Reopen the canonical DB before creating a new backend instance.  The
        # follow-up therefore has to recover both dialogue context and expert
        # evidence from durable state rather than process memory.
        reopened_database = DatabaseManager(database_path)
        reopened = ConversationStore(reopened_database)
        recovered = reopened.load_symbolic_projection(conversation.id)
        self.assertIsNotNone(recovered)
        assert recovered is not None
        recovered.assert_pure_symbolic()
        self.assertEqual(recovered.dialogue_act, "clarify")
        self.assertEqual(recovered.expert_evidence, expert_evidence)
        self.assertIn("partial_frame", recovered.dialogue_state["prolog_context_term"])

        reopened.save_message(
            case._message(
                conversation.id,
                5,
                "turn:complete-duration",
                MessageRole.USER,
                "5 minutes",
            )
        )
        completed = asyncio.run(
            self._symbolic_turn(
                reopened,
                conversation.id,
                "5 minutes",
                "turn:complete-duration",
            )
        )
        self.assertEqual(
            completed.response,
            "That action needs capability-checked execution before I can report success.",
        )
        self.assertTrue(completed.metadata["response_act"].startswith("dispatch_required("))
        reopened.save_message(
            case._message(
                conversation.id,
                6,
                "turn:complete-duration",
                MessageRole.ASSISTANT,
                completed.response,
            )
        )

        final_projection = reopened.load_symbolic_projection(conversation.id)
        self.assertIsNotNone(final_projection)
        assert final_projection is not None
        final_projection.assert_pure_symbolic()
        self.assertEqual(final_projection.projection_generation, 3)
        self.assertEqual(final_projection.runtime_generation, 3)
        self.assertEqual(final_projection.project_id, _PROJECT)
        self.assertEqual(final_projection.project_generation, 1)
        self.assertEqual(final_projection.dialogue_act, "dispatch_required")
        self.assertEqual(final_projection.expert_evidence, expert_evidence)
        self.assertIn(
            "completed_frame",
            final_projection.dialogue_state["prolog_context_term"],
        )
        self.assertEqual(final_projection.unresolved_questions, [])
        self.assertIs(final_projection.providers_enabled, False)
        self.assertEqual(final_projection.max_model_calls, 0)
        self.assertEqual(final_projection.provider_calls, 0)
        self.assertEqual(final_projection.model_calls, 0)

        from zara import __main__ as zara_cli

        replay = zara_cli._conversation_replay_payload(reopened, conversation.id)
        projection = replay["symbolic_projection"]
        self.assertIsNotNone(projection)
        assert projection is not None
        self.assertEqual(replay["version"], "ZARA-CONVERSATION-REPLAY/1")
        self.assertEqual(projection["dialogue_act"], "dispatch_required")
        self.assertEqual(projection["expert_evidence"], expert_evidence)
        self.assertIs(projection["providers_enabled"], False)
        self.assertEqual(projection["max_model_calls"], 0)
        self.assertEqual(projection["provider_calls"], 0)
        self.assertEqual(projection["model_calls"], 0)
        self.assertEqual(
            [message["content"] for message in replay["messages"]],
            [
                "Inspect this project with Prolog, Python, and Nim.",
                "The symbolic language inspection is ready.",
                "timer",
                "How long should I set the timer for?",
                "5 minutes",
                "That action needs capability-checked execution before I can report success.",
            ],
        )

        android = surface._android_twin(final_projection)
        self.assertEqual(android["projectId"], _PROJECT)
        self.assertEqual(android["projectGeneration"], 1)
        self.assertEqual(android["dialogueAct"], "dispatch_required")
        self.assertEqual(json.loads(android["expertEvidenceJson"]), expert_evidence)
        self.assertEqual(json.loads(android["unresolvedQuestionsJson"]), [])
        self.assertIn("completed_frame", android["dialogueStateJson"])
        self.assertIs(android["providersEnabled"], False)
        self.assertEqual(android["maxModelCalls"], 0)
        self.assertEqual(android["providerCalls"], 0)
        self.assertEqual(android["modelCalls"], 0)
        reopened_database.close()


if __name__ == "__main__":
    unittest.main()
