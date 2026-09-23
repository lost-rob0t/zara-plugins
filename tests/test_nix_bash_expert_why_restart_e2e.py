"""Gate persisted Nix/Bash expert evidence into a real symbolic why follow-up.

The reusable symbolic dialogue layer already knows how to explain a prior typed
expert answer without a model. This acceptance proves the product composition
can recover that prior answer from Zara's canonical conversation projection
after process recreation and route ``why?`` through the same symbolic runtime.
It deliberately adds no conversation store, expert registry, or provider path.
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

    server_facade = types.ModuleType("zara.server")
    server_facade.PrincipalContext = PrincipalContext
    sys.modules["zara.server"] = server_facade

from tests import test_nix_bash_durable_persistence_e2e as durable


CURRENT_DOTFILES = "3309c54ecb5f65c29374de6c60d2135a9ea2f94b"
CURRENT_ZARA_CORE = "eeef8ada909bf2c2a9a1ff4f29726648f5db60e5"
PROJECT_ID = "workspace:nix-bash:expert-why-restart"
SYMBOLIC_RENDERER = "symbolic-dcg/v1"

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
class NixBashExpertWhyRestartE2ETests(durable.NixBashDurablePersistenceE2ETests):
    @classmethod
    def setUpClass(cls) -> None:
        durable.EXPECTED_DOTFILES_COMMIT = CURRENT_DOTFILES
        durable.EXPECTED_ZARA_CORE_COMMIT = CURRENT_ZARA_CORE
        super().setUpClass()

    @staticmethod
    def _assert_zero_model(result: Any) -> None:
        assert result.metadata["route"] == "pure_symbolic"
        assert result.metadata["providers_enabled"] is False
        for key in (
            "max_provider_calls",
            "max_model_calls",
            "provider_calls",
            "model_calls",
        ):
            assert type(result.metadata[key]) is int
            assert result.metadata[key] == 0

    async def _why_turn(self, store: Any, conversation_id: str) -> Any:
        backend = PureSymbolicRuntimeBackend(
            projection_adapter=PureSymbolicProjectionAdapter(store)
        )
        await backend.start()
        try:
            result = await backend.submit_turn(
                "why?",
                turn_id="turn-nix-bash-why",
                conversation_id=conversation_id,
            )
            self._assert_zero_model(result)
            backend.commit_turn_result(
                result,
                turn_id="turn-nix-bash-why",
                conversation_id=conversation_id,
            )
            return result
        finally:
            await backend.stop()

    def test_persisted_expert_answer_routes_why_through_symbolic_followup(self) -> None:
        for name in durable.PROVIDER_CREDENTIALS:
            self.assertNotIn(name, os.environ)
        self._assert_android_contract()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expert_evidence = self._real_evidence(root / "expert-state")
            nix_evidence = next(
                item
                for item in expert_evidence
                if item["expert_id"] == "zara:expert/nix"
            )
            evidence_ref = nix_evidence["evidence_refs"][0]
            self.assertIs(type(evidence_ref), str)
            self.assertTrue(evidence_ref)
            self.assertEqual(nix_evidence["model_calls"], 0)
            self.assertEqual(nix_evidence["effect_receipts"], [])

            database_path = root / "conversation.db"
            database = DatabaseManager(database_path)
            store = ConversationStore(database)
            conversation = store.create_conversation(
                "Nix Bash expert why restart",
                conversation_id="conv-nix-bash-expert-why-restart",
            )
            prior_act = (
                "answer(expert,\"NixExpert inspected source.\",evidence('"
                + evidence_ref
                + "'))"
            )
            seeded = store.save_symbolic_projection(
                SymbolicConversationProjection(
                    conversation_id=conversation.id,
                    projection_generation=1,
                    runtime_generation=1,
                    turn_id="turn-nix-expert-answer",
                    outcome="success",
                    project_id=PROJECT_ID,
                    project_generation=1,
                    dialogue_act="expert.answer",
                    dialogue_state={
                        "active_project": PROJECT_ID,
                        "response_act_term": prior_act,
                        "prolog_context_term": "[]",
                        "prolog_context_project_id": PROJECT_ID,
                        "prolog_context_project_generation": 1,
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
            seeded.assert_pure_symbolic()
            database.close()

            reopened_database = DatabaseManager(database_path)
            reopened = ConversationStore(reopened_database)
            recovered = reopened.load_symbolic_projection(conversation.id)
            self.assertIsNotNone(recovered)
            assert recovered is not None
            recovered.assert_pure_symbolic()
            self.assertEqual(recovered.expert_evidence, expert_evidence)
            self.assertEqual(recovered.dialogue_state["response_act_term"], prior_act)

            result = asyncio.run(self._why_turn(reopened, conversation.id))
            self.assertEqual(
                result.response,
                f"I answered from evidence {evidence_ref}.",
                "persisted typed expert answer was not supplied to canonical symbolic follow-up",
            )

            current = reopened.load_symbolic_projection(conversation.id)
            self.assertIsNotNone(current)
            assert current is not None
            current.assert_pure_symbolic()
            self.assertEqual(current.expert_evidence, expert_evidence)
            self.assertEqual(current.provider_calls, 0)
            self.assertEqual(current.model_calls, 0)

            android = durable._android_twin(current)
            self.assertEqual(json.loads(android["expertEvidenceJson"]), expert_evidence)
            self.assertIs(android["providersEnabled"], False)
            self.assertEqual(android["maxModelCalls"], 0)
            self.assertEqual(android["providerCalls"], 0)
            self.assertEqual(android["modelCalls"], 0)
            reopened_database.close()


if __name__ == "__main__":
    durable.unittest.main()
