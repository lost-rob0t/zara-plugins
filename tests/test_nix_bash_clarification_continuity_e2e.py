"""Gate real Nix/Bash evidence across pure-symbolic clarification and restart.

This acceptance reuses Zara Core's canonical PureSymbolicRuntimeBackend,
ConversationStore projection owner, and the existing zara-expert language host.
It deliberately adds no registry, renderer, provider fallback, or history store.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import types
from pathlib import Path
from typing import Any


_ZARA_CORE_ROOT = os.environ.get("ZARA_CURRENT_CORE_ROOT")
if _ZARA_CORE_ROOT:
    sys.path.insert(0, str(Path(_ZARA_CORE_ROOT).resolve()))
    from zara.principals import PrincipalContext

    # Conversation persistence only needs the authenticated principal type. Keep
    # this acceptance on the canonical conversation owner without importing the
    # unrelated LangGraph/provider server stack.
    server_facade = types.ModuleType("zara.server")
    server_facade.PrincipalContext = PrincipalContext
    sys.modules["zara.server"] = server_facade

from tests import test_nix_bash_durable_persistence_e2e as durable


CURRENT_DOTFILES = "3309c54ecb5f65c29374de6c60d2135a9ea2f94b"
CURRENT_ZARA_CORE = "90fe62ba41af323f788e3046741cf5bcdc7bf848"
PROJECT_ID = "workspace:nix-bash:clarification-continuity"
SYMBOLIC_RENDERER = "symbolic-dcg/v1"

# Reuse the existing Nix/Bash evidence builder against exact current producers.
durable.EXPECTED_DOTFILES_COMMIT = CURRENT_DOTFILES
durable.EXPECTED_ZARA_CORE_COMMIT = CURRENT_ZARA_CORE

if durable.ZARA_CURRENT_CORE_ROOT:
    from zara.database import DatabaseManager
    from zara.desktop.conversation import ConversationStore, SymbolicConversationProjection
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

    def test_evidence_survives_clarification_restart_and_answer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expert_evidence = self._real_evidence(root / "expert-state")
            self.assertEqual(len(expert_evidence), 2)
            for item in expert_evidence:
                self.assertEqual(item["model_calls"], 0)
                self.assertEqual(item["effect_receipts"], [])

            database_path = root / "nix-bash-clarification.db"
            manager = DatabaseManager(database_path)
            store = ConversationStore(manager)
            conversation = store.create_conversation(
                "Nix Bash clarification continuity",
                conversation_id="conv-nix-bash-clarification",
            )
            expert_projection = store.save_symbolic_projection(
                SymbolicConversationProjection(
                    conversation_id=conversation.id,
                    projection_generation=1,
                    runtime_generation=1,
                    turn_id="turn-nix-bash-expert-answer",
                    outcome="success",
                    project_id=PROJECT_ID,
                    project_generation=1,
                    dialogue_act="expert.answer",
                    dialogue_state={
                        "active_project": PROJECT_ID,
                        "selected_experts": [
                            "zara:expert/nix",
                            "zara:expert/bash",
                        ],
                        "followups": ["why", "show evidence"],
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
            expert_projection.assert_pure_symbolic()
            self.assertNotIn(
                "prolog_context_project_id",
                expert_projection.dialogue_state,
            )
            self.assertNotIn(
                "prolog_context_project_generation",
                expert_projection.dialogue_state,
            )

            clarification = asyncio.run(
                self._symbolic_turn(
                    store,
                    conversation.id,
                    "timer",
                    "turn-nix-bash-clarify",
                )
            )
            self.assertEqual(
                clarification.response,
                "How long should I set the timer for?",
            )

            clarified = store.load_symbolic_projection(conversation.id)
            self.assertIsNotNone(clarified)
            clarified.assert_pure_symbolic()
            self.assertEqual(clarified.expert_evidence, expert_evidence)
            self.assertEqual(clarified.project_id, PROJECT_ID)
            self.assertEqual(clarified.project_generation, 1)
            self.assertEqual(clarified.dialogue_act, "clarify")
            self.assertTrue(
                any(
                    question.get("source") == "symbolic_dialogue"
                    for question in clarified.unresolved_questions
                )
            )
            self.assertIn("partial_frame", clarified.dialogue_state["prolog_context_term"])
            self.assertEqual(
                clarified.dialogue_state["prolog_context_project_id"],
                PROJECT_ID,
            )
            self.assertEqual(
                clarified.dialogue_state["prolog_context_project_generation"],
                1,
            )

            manager.close()

            restarted_manager = DatabaseManager(database_path)
            restarted_store = ConversationStore(restarted_manager)
            recovered = restarted_store.load_symbolic_projection(conversation.id)
            self.assertIsNotNone(recovered)
            recovered.assert_pure_symbolic()
            self.assertEqual(recovered.expert_evidence, expert_evidence)
            self.assertEqual(recovered.project_id, PROJECT_ID)
            self.assertEqual(recovered.project_generation, 1)
            self.assertEqual(recovered.dialogue_act, "clarify")
            self.assertIn("partial_frame", recovered.dialogue_state["prolog_context_term"])

            answer = asyncio.run(
                self._symbolic_turn(
                    restarted_store,
                    conversation.id,
                    "5 minutes",
                    "turn-nix-bash-answer",
                )
            )
            self.assertEqual(
                answer.response,
                "That action needs capability-checked execution before I can report success.",
            )
            self.assertTrue(answer.metadata["response_act"].startswith("dispatch_required("))

            answered = restarted_store.load_symbolic_projection(conversation.id)
            self.assertIsNotNone(answered)
            answered.assert_pure_symbolic()
            self.assertEqual(answered.expert_evidence, expert_evidence)
            self.assertEqual(answered.project_id, PROJECT_ID)
            self.assertEqual(answered.project_generation, 1)
            self.assertEqual(answered.dialogue_act, "dispatch_required")
            self.assertIn("completed_frame", answered.dialogue_state["prolog_context_term"])
            self.assertFalse(answered.providers_enabled)
            self.assertEqual(answered.max_model_calls, 0)
            self.assertEqual(answered.provider_calls, 0)
            self.assertEqual(answered.model_calls, 0)

            android = durable._android_twin(answered)
            self.assertEqual(android["expertEvidenceJson"], durable._canonical_json(expert_evidence))
            self.assertEqual(android["projectId"], PROJECT_ID)
            self.assertEqual(android["projectGeneration"], 1)
            self.assertEqual(android["dialogueAct"], "dispatch_required")
            self.assertFalse(android["providersEnabled"])
            self.assertEqual(android["maxModelCalls"], 0)
            self.assertEqual(android["providerCalls"], 0)
            self.assertEqual(android["modelCalls"], 0)
            restarted_manager.close()


if __name__ == "__main__":
    durable.unittest.main()
