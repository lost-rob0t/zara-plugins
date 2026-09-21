"""Current-head JS/TS/Java/Kotlin chain -> durable Zara symbolic conversation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import types
from dataclasses import replace
from pathlib import Path
from typing import Any

from tests import test_js_ts_java_kotlin_composition_fences_e2e as composition
from zara_expert.language_family import matching_experts


CURRENT_DOTFILES = "20e16c4fb084df4b01a17c06cd0e11ef5df2fb62"
CURRENT_ZARA_CORE = "dc74a41b216388662e55412e1e09a1c8c2fad5a7"
SUMMARY = "JavaScript, TypeScript, Java, and Kotlin inspection complete."
WORKSPACE = composition.WORKSPACE_ID
EXPERT_IDS = composition.EXPERT_IDS

composition.EXPECTED_DOTFILES_COMMIT = CURRENT_DOTFILES
composition.EXPECTED_ZARA_CORE_COMMIT = CURRENT_ZARA_CORE

if composition.ZARA_CURRENT_CORE_ROOT:
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


class JsTsJavaKotlinSymbolicConversationE2ETests(
    composition.JsTsJavaKotlinCompositionFencesE2ETests
):
    @classmethod
    def setUpClass(cls) -> None:
        composition.EXPECTED_DOTFILES_COMMIT = CURRENT_DOTFILES
        composition.EXPECTED_ZARA_CORE_COMMIT = CURRENT_ZARA_CORE
        super().setUpClass()

    @staticmethod
    def _message(conversation_id: str, sequence: int, turn_id: str, role, content: str):
        timestamp = f"2026-09-21T02:30:{sequence:02d}.000000"
        return MessageRecord(
            id=f"message-{sequence}",
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

    def test_four_expert_chain_persists_and_answers_why_after_restart(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        registry, core_invoker = self._core_composer()
        payloads = self._source_payloads()
        chain = dict(zip(EXPERT_IDS, EXPERT_IDS[1:]))

        routing = {
            "index.js": "zara:expert/javascript",
            "component.tsx": "zara:expert/typescript",
            "Main.java": "zara:expert/java",
            "Main.kt": "zara:expert/kotlin",
        }
        for path, expert_id in routing.items():
            self.assertEqual(matching_experts(path), (expert_id,))
        java_source = self.sources["java"][0].read_text(encoding="utf-8")
        kotlin_source = self.sources["kotlin"][0].read_text(encoding="utf-8")
        self.assertIn("project_metadata_role(observation_only).", java_source)
        self.assertIn("project_metadata_role(observation_only).", kotlin_source)
        self.assertNotIn("supports_semantic(coroutines).", java_source)
        self.assertIn("supports_semantic(coroutines).", kotlin_source)

        def chained_invoker(
            expert_id: str,
            operation: str,
            input_data: dict[str, Any],
            *,
            budget: composition.SharedSymbolicBudget,
            fence: composition.InvocationFence,
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
                    composition.DelegationRequest(
                        expert_id=child_id,
                        operation="inspect",
                        input=payloads[child_id],
                        reason=f"compose {expert_id} evidence into {child_id}",
                    ),
                ),
            )

        budget = composition.SharedSymbolicBudget(
            max_invocations=4,
            max_depth=3,
            max_evidence=64,
            max_model_calls=0,
        )
        root_node = composition.MetaExpertComposer(chained_invoker).invoke(
            EXPERT_IDS[0],
            "inspect",
            payloads[EXPERT_IDS[0]],
            budget=budget,
            fence=self._fence(),
        )
        nodes = [root_node]
        while nodes[-1].children:
            self.assertEqual(len(nodes[-1].children), 1)
            nodes.append(nodes[-1].children[0])
        self.assertEqual([node.expert_id for node in nodes], list(EXPERT_IDS))
        self.assertTrue(all(node.status == "succeeded" for node in nodes))
        self.assertEqual(budget.invocations_used, 4)
        self.assertEqual(budget.model_calls_used, 0)

        traces = [registry.explain(i) for i in registry.snapshot().invocation_ids]
        by_expert = {trace["expert_id"]: trace for trace in traces}
        self.assertEqual(set(by_expert), set(EXPERT_IDS))
        expert_evidence = []
        for expert_id in EXPERT_IDS:
            trace = by_expert[expert_id]
            self.assertEqual(trace["verdict"], "succeeded")
            self.assertTrue(trace["evidence_refs"])
            self.assertEqual(trace.get("effect_receipts", []), [])
            self.assertEqual(trace["usage"], {"model_calls": 0})
            expert_evidence.append(
                {
                    "expert_id": expert_id,
                    "invocation_id": trace["invocation_id"],
                    "evidence_refs": list(trace["evidence_refs"]),
                    "verdict": trace["verdict"],
                    "model_calls": 0,
                }
            )

        root_ref = by_expert[EXPERT_IDS[0]]["evidence_refs"][0]
        answer, _why = self._dialogue(root_ref)
        self.assertEqual(answer, SUMMARY)

        database_path = root / "conversation.db"
        database = DatabaseManager(database_path)
        store = ConversationStore(database)
        conversation = store.create_conversation(
            "Pure symbolic JS/TS + Java/Kotlin chain",
            conversation_id="conversation:js-ts-java-kotlin",
        )
        store.save_message(
            self._message(
                conversation.id,
                1,
                "turn:inspect",
                MessageRole.USER,
                "Inspect this JavaScript and follow the language chain.",
            )
        )
        store.save_message(
            self._message(
                conversation.id,
                2,
                "turn:inspect",
                MessageRole.ASSISTANT,
                answer,
            )
        )
        first = store.save_symbolic_projection(
            SymbolicConversationProjection(
                conversation_id=conversation.id,
                projection_generation=1,
                runtime_generation=1,
                turn_id="turn:inspect",
                outcome="success",
                project_id=WORKSPACE,
                project_generation=composition.WORKSPACE_GENERATION,
                dialogue_act="expert.answer",
                dialogue_state={
                    "root_expert": EXPERT_IDS[0],
                    "selected_experts": list(EXPERT_IDS),
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
        recovered_root_ref = recovered.expert_evidence[0]["evidence_refs"][0]
        _answer, why = self._dialogue(recovered_root_ref)
        self.assertEqual(why, f"I answered from evidence {recovered_root_ref}.")
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
                project_id=WORKSPACE,
                project_generation=composition.WORKSPACE_GENERATION,
                dialogue_act="explain",
                dialogue_state={
                    "follow_up": "why",
                    "evidence_ref": recovered_root_ref,
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
        self.assertEqual(final.expert_evidence, expert_evidence)
        self.assertEqual(final.provider_calls, 0)
        self.assertEqual(final.model_calls, 0)
        self.assertEqual(
            [message.content for message in final_store.load_messages(conversation.id)],
            [
                "Inspect this JavaScript and follow the language chain.",
                answer,
                "why did you do that?",
                why,
            ],
        )
        final_database.close()
