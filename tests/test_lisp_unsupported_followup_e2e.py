"""Fail closed on unsupported Lisp follow-ups after durable restart."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from tests import test_lisp_symbolic_conversation_e2e as conversation
from tests import test_prolog_python_nim_surface_parity_e2e as surface


CURRENT_DOTFILES = "97534b85f96a5ae7962762268440fb9ae7815ae0"
CURRENT_ZARA_CORE = "5cb27a3504720d98f978130bd7317727ba334c70"
_UNSUPPORTED_TEXT = "I don’t know how to handle that symbolically yet."


def _unsupported_follow_up(zara_core_root: Path, evidence_ref: str) -> str:
    module = zara_core_root / "modules" / "symbolic_dialogue.pl"
    if not module.is_file():
        raise AssertionError(f"missing canonical symbolic renderer: {module}")
    goal = (
        f"EvidenceRef={conversation.json.dumps(evidence_ref)},"
        f"Summary={conversation.json.dumps(conversation.SUMMARY)},"
        f"use_module('{module.as_posix()}'),"
        "symbolic_dialogue:symbolic_follow_up("
        '\"use an llm to guess whether you fixed it\",'
        "answer(expert,Summary,evidence(EvidenceRef)),Reply,Evidence),"
        "Evidence=evidence(renderer('symbolic-dcg/v1'),provider_calls(0),model_calls(0)),"
        "format('~s~n',[Reply]),halt(0)"
    )
    completed = subprocess.run(
        ["swipl", "-q", "-g", goal],
        cwd=zara_core_root,
        env=conversation._provider_free_env(),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "canonical symbolic follow-up renderer failed: "
            f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
        )
    return completed.stdout.strip()


@conversation.lisp.unittest.skipUnless(
    conversation.lisp.DOTFILES_ROOT and conversation.lisp.ZARA_CORE_ROOT,
    "exact Dotfiles and Zara Core checkouts not provided",
)
class LispUnsupportedFollowUpE2ETests(conversation.LispSymbolicConversationE2ETests):
    @classmethod
    def setUpClass(cls) -> None:
        conversation.CURRENT_DOTFILES = CURRENT_DOTFILES
        conversation.CURRENT_ZARA_CORE = CURRENT_ZARA_CORE
        conversation.lisp.EXPECTED_DOTFILES_COMMIT = CURRENT_DOTFILES
        conversation.lisp.EXPECTED_ZARA_CORE_COMMIT = CURRENT_ZARA_CORE
        super().setUpClass()

    def test_unsupported_follow_up_after_restart_never_uses_provider_or_stale_success(self) -> None:
        for name in conversation._PROVIDER_CREDENTIALS:
            self.assertNotIn(name, os.environ)

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        registry, handles = self._runtime()
        composer = self._composer(registry, handles)
        budget = conversation.lisp.SharedSymbolicBudget(
            max_invocations=2,
            max_depth=1,
            max_model_calls=0,
        )

        source = "(defun demo (x) (list x"
        tree = composer.invoke(
            "zara:expert/common-lisp",
            "repair.preview",
            {"arguments": [source, "diagnostic:lisp:missing-close"]},
            budget=budget,
            fence=self._fence(),
        )
        self.assertEqual(tree.status, "unknown")
        self.assertEqual(len(tree.children), 1)
        child = tree.children[0]
        self.assertEqual(child.status, "succeeded")
        self.assertTrue(child.evidence)
        self.assertEqual(budget.model_calls_used, 0)

        invocation_ids = registry.snapshot().invocation_ids
        self.assertEqual(len(invocation_ids), 1)
        trace = registry.explain(invocation_ids[0])
        self.assertEqual(trace["expert_id"], "zara:expert/lisp")
        self.assertEqual(trace["verdict"], "succeeded")
        self.assertEqual(trace.get("effect_receipts", []), [])
        self.assertEqual(trace["usage"]["model_calls"], 0)
        evidence_ref = trace["evidence_refs"][0]
        answer, _why = self._dialogue(evidence_ref)

        database_path = root / "conversation.db"
        database = conversation.DatabaseManager(database_path)
        store = conversation.ConversationStore(database)
        chat = store.create_conversation(
            "Pure symbolic Lisp unsupported follow-up",
            conversation_id="conversation:lisp-unsupported-followup",
        )
        store.save_message(
            self._message(
                chat.id,
                1,
                "turn:repair-preview",
                conversation.MessageRole.USER,
                "Can you fix the missing parenthesis in this Common Lisp form?",
            )
        )
        store.save_message(
            self._message(
                chat.id,
                2,
                "turn:repair-preview",
                conversation.MessageRole.ASSISTANT,
                answer,
            )
        )
        initial_evidence = [
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
        first = store.save_symbolic_projection(
            conversation.SymbolicConversationProjection(
                conversation_id=chat.id,
                projection_generation=1,
                runtime_generation=1,
                turn_id="turn:repair-preview",
                outcome="success",
                project_id=self.WORKSPACE,
                project_generation=1,
                dialogue_act="expert.answer",
                dialogue_state={
                    "repair_status": "proposed",
                    "effect_committed": False,
                    "fresh_postcondition_verified": False,
                },
                expert_evidence=initial_evidence,
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

        reopened_database = conversation.DatabaseManager(database_path)
        reopened = conversation.ConversationStore(reopened_database)
        recovered = reopened.load_symbolic_projection(chat.id)
        self.assertIsNotNone(recovered)
        assert recovered is not None
        recovered.assert_pure_symbolic()
        self.assertEqual(recovered.expert_evidence, initial_evidence)
        self.assertIs(recovered.dialogue_state["effect_committed"], False)
        self.assertIs(recovered.dialogue_state["fresh_postcondition_verified"], False)

        reply = _unsupported_follow_up(self.zara_core_root, evidence_ref)
        self.assertEqual(reply, _UNSUPPORTED_TEXT)
        reopened.save_message(
            self._message(
                chat.id,
                3,
                "turn:unsupported",
                conversation.MessageRole.USER,
                "Use an LLM to guess whether you fixed it.",
            )
        )
        reopened.save_message(
            self._message(
                chat.id,
                4,
                "turn:unsupported",
                conversation.MessageRole.ASSISTANT,
                reply,
            )
        )
        unsupported = reopened.save_symbolic_projection(
            conversation.SymbolicConversationProjection(
                conversation_id=chat.id,
                projection_generation=2,
                runtime_generation=2,
                turn_id="turn:unsupported",
                outcome="unknown",
                project_id=self.WORKSPACE,
                project_generation=1,
                dialogue_act="unsupported",
                dialogue_state={
                    "unsupported_reason": "no_symbolic_route",
                    "effect_committed": False,
                    "fresh_postcondition_verified": False,
                    "prior_expert_evidence_reused": False,
                },
                expert_evidence=[],
                renderer_provenance="symbolic-dcg/v1",
                providers_enabled=False,
                max_model_calls=0,
                provider_calls=0,
                model_calls=0,
            ),
            expected_generation=recovered.projection_generation,
        )
        unsupported.assert_pure_symbolic()
        self.assertEqual(unsupported.outcome, "unknown")
        self.assertEqual(unsupported.dialogue_act, "unsupported")
        self.assertEqual(unsupported.expert_evidence, [])
        self.assertFalse(unsupported.providers_enabled)
        self.assertEqual(unsupported.max_model_calls, 0)
        self.assertEqual(unsupported.provider_calls, 0)
        self.assertEqual(unsupported.model_calls, 0)
        self.assertIs(unsupported.dialogue_state["effect_committed"], False)
        self.assertIs(unsupported.dialogue_state["fresh_postcondition_verified"], False)
        self.assertIs(unsupported.dialogue_state["prior_expert_evidence_reused"], False)

        android = surface._android_twin(unsupported)
        self.assertEqual(android["outcome"], "unknown")
        self.assertEqual(android["dialogueAct"], "unsupported")
        self.assertEqual(android["expertEvidenceJson"], "[]")
        self.assertFalse(android["providersEnabled"])
        self.assertEqual(android["maxModelCalls"], 0)
        self.assertEqual(android["providerCalls"], 0)
        self.assertEqual(android["modelCalls"], 0)
        reopened_database.close()

        final_database = conversation.DatabaseManager(database_path)
        final_store = conversation.ConversationStore(final_database)
        final = final_store.load_symbolic_projection(chat.id)
        self.assertIsNotNone(final)
        assert final is not None
        final.assert_pure_symbolic()
        self.assertEqual(final.outcome, "unknown")
        self.assertEqual(final.dialogue_act, "unsupported")
        self.assertEqual(final.expert_evidence, [])
        self.assertEqual(final.provider_calls, 0)
        self.assertEqual(final.model_calls, 0)
        self.assertIs(final.dialogue_state["effect_committed"], False)
        self.assertIs(final.dialogue_state["fresh_postcondition_verified"], False)
        self.assertEqual(
            [message.content for message in final_store.load_messages(chat.id)],
            [
                "Can you fix the missing parenthesis in this Common Lisp form?",
                answer,
                "Use an LLM to guess whether you fixed it.",
                _UNSUPPORTED_TEXT,
            ],
        )
        final_database.close()


if __name__ == "__main__":
    conversation.lisp.unittest.main()
