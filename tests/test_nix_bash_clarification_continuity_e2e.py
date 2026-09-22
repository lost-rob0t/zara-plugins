"""Gate real Nix/Bash evidence across pure-symbolic clarification and restart.

This acceptance reuses Zara Core's canonical PureSymbolicRuntimeBackend,
ConversationStore projection owner, and the existing zara-expert language host.
It deliberately adds no registry, renderer, provider fallback, or history store.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from tests import test_nix_bash_durable_persistence_e2e as durable


CURRENT_DOTFILES = "3309c54ecb5f65c29374de6c60d2135a9ea2f94b"
CURRENT_ZARA_CORE = "00b3d7ce39f925b504f9094908e97ff42ae7a169"
PROJECT_ID = "workspace:nix-bash:clarification-continuity"
SYMBOLIC_RENDERER = "symbolic-dcg/v1"

# Reuse the existing Nix/Bash evidence builder against exact current producers.
durable.EXPECTED_DOTFILES_COMMIT = CURRENT_DOTFILES
durable.EXPECTED_ZARA_CORE_COMMIT = CURRENT_ZARA_CORE

if durable.ZARA_CURRENT_CORE_ROOT:
    from zara.database import DatabaseManager
    from zara.desktop.conversation import ConversationStore, SymbolicConversationProjection
    from zara.desktop.conversation.models import MessageRecord, MessageRole, MessageStatus
    from zara.desktop.conversation.symbolic_runtime import PureSymbolicProjectionAdapter
    from zara.runtime.pure_symbolic_backend import PureSymbolicRuntimeBackend


@durable.unittest.skipUnless(
    durable.DOTFILES_ROOT and durable.ZARA_CURRENT_CORE_ROOT,
    "exact Dotfiles and current Zara Core checkouts not provided",
)
class NixBashClarificationContinuityE2ETests(
    durable.NixBashDurablePersistenceE2ETests
):
    @classmethod
    def setUpClass(cls) -> None:
        durable.EXPECTED_DOTFILES_COMMIT = CURRENT_DOTFILES
        durable.EXPECTED_ZARA_CORE_COMMIT = CURRENT_ZARA_CORE
        super().setUpClass()

    @staticmethod
    def _message(
        conversation_id: str,
        sequence: int,
        turn_id: str,
        role: Any,
        content: str,
    ) -> Any:
        timestamp = f"2026-09-22T22:20:{sequence:02d}.000000"
        return MessageRecord(
            id=f"nix-bash-clarification-message-{sequence}",
            conversation_id=conversation_id,
            sequence=sequence,
            turn_id=turn_id,
            role=role,
            content=content,
            status=MessageStatus.COMPLETE,
            created_at=timestamp,
            updated_at=timestamp,
        )

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

    def test_real_nix_bash_evidence_survives_clarification_restart_and_followup(self) -> None:
        for name in durable.PROVIDER_CREDENTIALS:
            self.assertNotIn(name, os.environ)
        self._assert_android_contract()

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        expert_evidence = self._real_evidence(root / "expert-state")
        self.assertEqual(
            {item["expert_id"] for item in expert_evidence},
            {"zara:expert/nix", "zara:expert/bash"},
        )
        for item in expert_evidence:
            self.assertEqual(item["verdict"], "succeeded")
            self.assertTrue(item["evidence_refs"])
            self.assertEqual(item["model_calls"], 0)
            self.assertEqual(item["effect_receipts"], [])

        database_path = root / "conversation.db"
        database = DatabaseManager(database_path)
        store = ConversationStore(database)
        conversation = store.create_conversation(
            "Nix Bash clarification continuity",
            conversation_id="conversation:nix-bash:clarification-continuity",
        )
        store.save_message(
            self._message(
                conversation.id,
                1,
                "turn:nix-bash-inspect",
                MessageRole.USER,
                "Inspect this project with Nix and Bash.",
            )
        )
        store.save_message(
            self._message(
                conversation.id,
                2,
                "turn:nix-bash-inspect",
                MessageRole.ASSISTANT,
                "The symbolic Nix and Bash inspection is ready.",
            )
        )
        initial = store.save_symbolic_projection(
            SymbolicConversationProjection(
                conversation_id=conversation.id,
                projection_generation=1,
                runtime_generation=1,
                turn_id="turn:nix-bash-inspect",
                outcome="success",
                project_id=PROJECT_ID,
                project_generation=1,
                dialogue_act="expert.answer",
                dialogue_state={
                    "active_project": PROJECT_ID,
                    "selected_experts": ["zara:expert/nix", "zara:expert/bash"],
                },
                expert_evidence=expert_evidence,
                renderer_provenance=SYMBOLIC_RENDERER,
                providers_enabled=False,
                max_model_calls=0,
                provider_calls=0,
                model_calls=0,
            ),
            expected_generation=0,
        )
        initial.assert_pure_symbolic()

        store.save_message(
            self._message(
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
            self._message(
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
        self.assertEqual(clarified.project_id, PROJECT_ID)
        self.assertEqual(clarified.project_generation, 1)
        self.assertEqual(clarified.dialogue_act, "clarify")
        self.assertEqual(clarified.expert_evidence, expert_evidence)
        self.assertIn("partial_frame", clarified.dialogue_state["prolog_context_term"])
        self.assertEqual(len(clarified.unresolved_questions), 1)
        self.assertEqual(
            clarified.unresolved_questions[0]["text"],
            "How long should I set the timer for?",
        )
        self.assertIs(clarified.providers_enabled, False)
        self.assertEqual(clarified.max_model_calls, 0)
        self.assertEqual(clarified.provider_calls, 0)
        self.assertEqual(clarified.model_calls, 0)
        database.close()

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
            self._message(
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
            self._message(
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
        self.assertEqual(final_projection.project_id, PROJECT_ID)
        self.assertEqual(final_projection.project_generation, 1)
        self.assertEqual(final_projection.dialogue_act, "dispatch_required")
        self.assertEqual(final_projection.expert_evidence, expert_evidence)
        self.assertIn("completed_frame", final_projection.dialogue_state["prolog_context_term"])
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
                "Inspect this project with Nix and Bash.",
                "The symbolic Nix and Bash inspection is ready.",
                "timer",
                "How long should I set the timer for?",
                "5 minutes",
                "That action needs capability-checked execution before I can report success.",
            ],
        )

        android = durable._android_twin(final_projection)
        self.assertEqual(android["projectId"], PROJECT_ID)
        self.assertEqual(android["projectGeneration"], 1)
        self.assertEqual(android["dialogueAct"], "dispatch_required")
        self.assertEqual(json.loads(android["expertEvidenceJson"]), expert_evidence)
        self.assertIs(android["providersEnabled"], False)
        self.assertEqual(android["maxModelCalls"], 0)
        self.assertEqual(android["providerCalls"], 0)
        self.assertEqual(android["modelCalls"], 0)
        reopened_database.close()


if __name__ == "__main__":
    durable.unittest.main()
