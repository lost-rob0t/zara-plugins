"""Real Lisp repair preview -> durable Zara pure-symbolic conversation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

from tests import test_lisp_current_core_delegation_e2e as lisp


CURRENT_DOTFILES = "97534b85f96a5ae7962762268440fb9ae7815ae0"
CURRENT_ZARA_CORE = "dc74a41b216388662e55412e1e09a1c8c2fad5a7"
SUMMARY = (
    "I can propose the structural Common Lisp parenthesis repair, "
    "but I need fresh SBCL verification before I call it fixed."
)

lisp.EXPECTED_DOTFILES_COMMIT = CURRENT_DOTFILES
lisp.EXPECTED_ZARA_CORE_COMMIT = CURRENT_ZARA_CORE

if lisp.ZARA_CORE_ROOT:
    from zara.principals import PrincipalContext

    server_facade = types.ModuleType("zara.server")
    server_facade.PrincipalContext = PrincipalContext
    sys.modules["zara.server"] = server_facade

    from zara.database import DatabaseManager
    from zara.desktop.conversation import ConversationStore, SymbolicConversationProjection
    from zara.desktop.conversation.models import MessageRecord, MessageRole, MessageStatus


_PROVIDER_CREDENTIALS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "ZAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "HF_TOKEN",
)


def _provider_free_env() -> dict[str, str]:
    env = os.environ.copy()
    for name in _PROVIDER_CREDENTIALS:
        env.pop(name, None)
    return env


@lisp.unittest.skipUnless(
    lisp.DOTFILES_ROOT and lisp.ZARA_CORE_ROOT,
    "exact Dotfiles and Zara Core checkouts not provided",
)
class LispSymbolicConversationE2ETests(lisp.LispCurrentCoreDelegationE2ETests):
    @classmethod
    def setUpClass(cls) -> None:
        lisp.EXPECTED_DOTFILES_COMMIT = CURRENT_DOTFILES
        lisp.EXPECTED_ZARA_CORE_COMMIT = CURRENT_ZARA_CORE
        super().setUpClass()

    @staticmethod
    def _message(conversation_id: str, sequence: int, turn_id: str, role, content: str):
        timestamp = f"2026-09-21T03:55:{sequence:02d}.000000"
        return MessageRecord(
            id=f"lisp-message-{sequence}",
            conversation_id=conversation_id,
            sequence=sequence,
            turn_id=turn_id,
            role=role,
            content=content,
            status=MessageStatus.COMPLETE,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _dialogue(self, evidence_ref: str) -> tuple[str, str]:
        goal = (
            f"EvidenceRef={json.dumps(evidence_ref)},"
            f"Summary={json.dumps(SUMMARY)},"
            "symbolic_dialogue:response_act("
            "expert_result(summary(Summary),evidence(EvidenceRef)),Act),"
            "symbolic_dialogue:render_response(Act,Answer),"
            "symbolic_dialogue:symbolic_follow_up("
            '\"why did you do that?\",Act,Why,WhyEvidence),'
            "WhyEvidence=evidence(renderer('symbolic-dcg/v1'),provider_calls(0),model_calls(0)),"
            "format('~s~n~s~n',[Answer,Why]),halt(0)"
        )
        completed = subprocess.run(
            [
                "swipl",
                "-q",
                "-s",
                str(self.zara_core_root / "modules" / "symbolic_dialogue.pl"),
                "-g",
                goal,
                "-t",
                "halt(1)",
            ],
            cwd=self.zara_core_root,
            env=_provider_free_env(),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        lines = completed.stdout.splitlines()
        self.assertEqual(len(lines), 2, completed.stdout + completed.stderr)
        return lines[0], lines[1]

    def test_common_lisp_repair_preview_survives_restart_and_explains_itself(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        registry, handles = self._runtime()
        composer = self._composer(registry, handles)
        budget = lisp.SharedSymbolicBudget(
            max_invocations=2,
            max_depth=1,
            max_model_calls=0,
        )

        source = "(defun demo (x) (list x"
        tree = composer.invoke(
            "zara:expert/common-lisp",
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

        invocation_ids = registry.snapshot().invocation_ids
        self.assertEqual(len(invocation_ids), 1)
        trace = registry.explain(invocation_ids[0])
        self.assertEqual(trace["expert_id"], "zara:expert/lisp")
        self.assertEqual(trace["verdict"], "succeeded")
        self.assertTrue(trace["evidence_refs"])
        self.assertEqual(trace.get("effect_receipts", []), [])
        self.assertIs(type(trace["usage"]["model_calls"]), int)
        self.assertEqual(trace["usage"]["model_calls"], 0)

        evidence_ref = trace["evidence_refs"][0]
        answer, _why = self._dialogue(evidence_ref)
        self.assertEqual(answer, SUMMARY)

        expert_evidence = [
            {
                "expert_id": "zara:expert/common-lisp",
                "operation": "repair.preview",
                "verdict": tree.status,
                "delegated_to": "zara:expert/lisp",
                "model_calls": 0,
            },
            {
                "expert_id": trace["expert_id"],
                "invocation_id": trace["invocation_id"],
                "operation": "repair.preview",
                "verdict": trace["verdict"],
                "evidence_refs": list(trace["evidence_refs"]),
                "effect_receipts": [],
                "model_calls": 0,
            },
        ]

        database_path = root / "conversation.db"
        database = DatabaseManager(database_path)
        store = ConversationStore(database)
        conversation = store.create_conversation(
            "Pure symbolic Common Lisp repair",
            conversation_id="conversation:lisp-repair",
        )
        store.save_message(
            self._message(
                conversation.id,
                1,
                "turn:repair-preview",
                MessageRole.USER,
                "Can you fix the missing parenthesis in this Common Lisp form?",
            )
        )
        store.save_message(
            self._message(
                conversation.id,
                2,
                "turn:repair-preview",
                MessageRole.ASSISTANT,
                answer,
            )
        )
        first = store.save_symbolic_projection(
            SymbolicConversationProjection(
                conversation_id=conversation.id,
                projection_generation=1,
                runtime_generation=1,
                turn_id="turn:repair-preview",
                outcome="success",
                project_id=self.WORKSPACE,
                project_generation=1,
                dialogue_act="expert.answer",
                dialogue_state={
                    "requested_expert": "zara:expert/common-lisp",
                    "delegated_expert": "zara:expert/lisp",
                    "repair_status": "proposed",
                    "effect_committed": False,
                    "fresh_postcondition_verified": False,
                },
                expert_evidence=expert_evidence,
                renderer_provenance="symbolic-dcg/v1",
                providers_enabled=False,
                max_model_calls=0,
                provider_calls=0,
                model_calls=0,
            ),
            expected_generation=0,
        )
        first.assert_pure_symbolic()
        database.close()

        reopened_database = DatabaseManager(database_path)
        reopened = ConversationStore(reopened_database)
        recovered = reopened.load_symbolic_projection(conversation.id)
        self.assertIsNotNone(recovered)
        assert recovered is not None
        recovered.assert_pure_symbolic()
        self.assertEqual(recovered.expert_evidence, expert_evidence)
        self.assertIs(recovered.dialogue_state["effect_committed"], False)
        self.assertIs(recovered.dialogue_state["fresh_postcondition_verified"], False)

        recovered_ref = recovered.expert_evidence[1]["evidence_refs"][0]
        _answer, why = self._dialogue(recovered_ref)
        self.assertEqual(why, f"I answered from evidence {recovered_ref}.")
        reopened.save_message(
            self._message(
                conversation.id,
                3,
                "turn:why",
                MessageRole.USER,
                "why did you do that?",
            )
        )
        reopened.save_message(
            self._message(
                conversation.id,
                4,
                "turn:why",
                MessageRole.ASSISTANT,
                why,
            )
        )
        second = reopened.save_symbolic_projection(
            SymbolicConversationProjection(
                conversation_id=conversation.id,
                projection_generation=2,
                runtime_generation=2,
                turn_id="turn:why",
                outcome="success",
                project_id=self.WORKSPACE,
                project_generation=1,
                dialogue_act="explain",
                dialogue_state={
                    "follow_up": "why",
                    "evidence_ref": recovered_ref,
                    "effect_committed": False,
                    "fresh_postcondition_verified": False,
                },
                expert_evidence=recovered.expert_evidence,
                renderer_provenance="symbolic-dcg/v1",
                providers_enabled=False,
                max_model_calls=0,
                provider_calls=0,
                model_calls=0,
            ),
            expected_generation=first.projection_generation,
        )
        second.assert_pure_symbolic()
        reopened_database.close()

        final_database = DatabaseManager(database_path)
        final_store = ConversationStore(final_database)
        final = final_store.load_symbolic_projection(conversation.id)
        self.assertIsNotNone(final)
        assert final is not None
        final.assert_pure_symbolic()
        self.assertEqual(final.dialogue_act, "explain")
        self.assertEqual(final.provider_calls, 0)
        self.assertEqual(final.model_calls, 0)
        self.assertIs(final.dialogue_state["effect_committed"], False)
        self.assertIs(final.dialogue_state["fresh_postcondition_verified"], False)
        self.assertEqual(
            [message.content for message in final_store.load_messages(conversation.id)],
            [
                "Can you fix the missing parenthesis in this Common Lisp form?",
                answer,
                "why did you do that?",
                why,
            ],
        )
        final_database.close()


if __name__ == "__main__":
    lisp.unittest.main()
