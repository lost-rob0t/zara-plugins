"""Gate fail-closed unsupported follow-ups after project switch and restart."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import test_prolog_python_nim_surface_parity_e2e as surface


EXPECTED_DOTFILES_COMMIT = "97534b85f96a5ae7962762268440fb9ae7815ae0"
EXPECTED_ZARA_CORE_COMMIT = "9ff68d63b76c1db39689867f848d47c83c49cbcc"
_PROJECT_A = "workspace:prolog-python-nim:A"
_PROJECT_B = "workspace:prolog-python-nim:B"
_UNSUPPORTED_TEXT = "I don’t know how to handle that symbolically yet."


def _render_unsupported_follow_up(zara_core_root: Path) -> str:
    module = zara_core_root / "modules" / "symbolic_dialogue.pl"
    if not module.is_file():
        raise AssertionError(f"missing canonical symbolic renderer: {module}")
    goal = (
        f"use_module('{module.as_posix()}'),"
        "symbolic_dialogue:symbolic_follow_up("
        '"use an llm to guess what I mean",'
        "clarify(reference_not_found),Reply,Evidence),"
        "Evidence=evidence(renderer('symbolic-dcg/v1'),provider_calls(0),model_calls(0)),"
        "format('~s~n',[Reply]),halt(0)"
    )
    completed = subprocess.run(
        ["swipl", "-q", "-g", goal],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "canonical symbolic renderer failed: "
            f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
        )
    return completed.stdout.strip()


@unittest.skipUnless(
    surface.DOTFILES_ROOT and surface.ZARA_CORE_ROOT,
    "exact Dotfiles and Zara Core checkouts not provided",
)
class PrologPythonNimUnsupportedFollowUpE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        surface.EXPECTED_DOTFILES_COMMIT = EXPECTED_DOTFILES_COMMIT
        surface.EXPECTED_ZARA_CORE_COMMIT = EXPECTED_ZARA_CORE_COMMIT
        surface.PrologPythonNimSurfaceParityE2ETests.setUpClass()
        cls.helper = surface.PrologPythonNimSurfaceParityE2ETests(
            methodName=(
                "test_project_switch_fences_old_expert_context_on_both_surface_contracts"
            )
        )
        cls.zara_core_root = Path(surface.ZARA_CORE_ROOT).resolve()

    def test_unsupported_follow_up_after_switch_and_restart_fails_closed(self) -> None:
        for name in surface._PROVIDER_CREDENTIALS:
            self.assertNotIn(name, os.environ)

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        expert_evidence = self.helper._real_chain(root / "expert-state")

        database_path = root / "conversation.db"
        database = surface.DatabaseManager(database_path)
        store = surface.ConversationStore(database)
        conversation = store.create_conversation(
            "Unsupported follow-up after project switch",
            conversation_id="conversation:unsupported-followup",
        )
        store.save_message(
            self.helper._message(
                conversation.id,
                1,
                "turn:project-a",
                surface.MessageRole.USER,
                "Inspect project A using Prolog, Python, and Nim.",
            )
        )
        store.save_message(
            self.helper._message(
                conversation.id,
                2,
                "turn:project-a",
                surface.MessageRole.ASSISTANT,
                "Project A language inspection is complete.",
            )
        )
        project_a = store.save_symbolic_projection(
            surface.SymbolicConversationProjection(
                conversation_id=conversation.id,
                projection_generation=1,
                runtime_generation=1,
                turn_id="turn:project-a",
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
                },
                expert_evidence=expert_evidence,
                renderer_provenance=surface._SYMBOLIC_RENDERER,
                providers_enabled=False,
                max_model_calls=0,
                provider_calls=0,
                model_calls=0,
            ),
            expected_generation=0,
        )
        project_a.assert_pure_symbolic()

        store.save_message(
            self.helper._message(
                conversation.id,
                3,
                "turn:project-switch",
                surface.MessageRole.USER,
                "Switch to project B. What about the prior result?",
            )
        )
        store.save_message(
            self.helper._message(
                conversation.id,
                4,
                "turn:project-switch",
                surface.MessageRole.ASSISTANT,
                "Which project B result should I use?",
            )
        )
        project_b = store.save_symbolic_projection(
            surface.SymbolicConversationProjection(
                conversation_id=conversation.id,
                projection_generation=2,
                runtime_generation=2,
                turn_id="turn:project-switch",
                outcome="success",
                project_id=_PROJECT_B,
                project_generation=2,
                dialogue_act="clarify",
                dialogue_state={
                    "active_project": _PROJECT_B,
                    "previous_project": _PROJECT_A,
                    "stale_context_fenced": True,
                },
                unresolved_questions=[
                    {
                        "kind": "project_context",
                        "project_id": _PROJECT_B,
                        "prompt": "Which project B result should I use?",
                    }
                ],
                expert_evidence=[],
                renderer_provenance=surface._SYMBOLIC_RENDERER,
                providers_enabled=False,
                max_model_calls=0,
                provider_calls=0,
                model_calls=0,
            ),
            expected_generation=project_a.projection_generation,
        )
        project_b.assert_pure_symbolic()
        database.close()

        reopened_database = surface.DatabaseManager(database_path)
        reopened = surface.ConversationStore(reopened_database)
        recovered = reopened.load_symbolic_projection(conversation.id)
        self.assertIsNotNone(recovered)
        assert recovered is not None
        recovered.assert_pure_symbolic()
        self.assertEqual(recovered.project_id, _PROJECT_B)
        self.assertEqual(recovered.project_generation, 2)
        self.assertEqual(recovered.dialogue_act, "clarify")
        self.assertEqual(recovered.expert_evidence, [])

        reply = _render_unsupported_follow_up(self.zara_core_root)
        self.assertEqual(reply, _UNSUPPORTED_TEXT)
        reopened.save_message(
            self.helper._message(
                conversation.id,
                5,
                "turn:unsupported",
                surface.MessageRole.USER,
                "Use an LLM to guess what I mean.",
            )
        )
        reopened.save_message(
            self.helper._message(
                conversation.id,
                6,
                "turn:unsupported",
                surface.MessageRole.ASSISTANT,
                reply,
            )
        )
        unsupported = reopened.save_symbolic_projection(
            surface.SymbolicConversationProjection(
                conversation_id=conversation.id,
                projection_generation=3,
                runtime_generation=3,
                turn_id="turn:unsupported",
                # Execution outcome remains canonical; the dialogue act carries unsupported semantics.
                outcome="unknown",
                project_id=_PROJECT_B,
                project_generation=2,
                dialogue_act="unsupported",
                dialogue_state={
                    "active_project": _PROJECT_B,
                    "unsupported_reason": "no_symbolic_route",
                    "stale_context_fenced": True,
                },
                unresolved_questions=[],
                expert_evidence=[],
                renderer_provenance=surface._SYMBOLIC_RENDERER,
                providers_enabled=False,
                max_model_calls=0,
                provider_calls=0,
                model_calls=0,
            ),
            expected_generation=recovered.projection_generation,
        )
        unsupported.assert_pure_symbolic()
        self.assertEqual(unsupported.outcome, "unknown")
        self.assertEqual(unsupported.expert_evidence, [])
        self.assertFalse(unsupported.providers_enabled)
        self.assertEqual(unsupported.max_model_calls, 0)
        self.assertEqual(unsupported.provider_calls, 0)
        self.assertEqual(unsupported.model_calls, 0)

        android_twin = surface._android_twin(unsupported)
        self.assertEqual(android_twin["projectId"], _PROJECT_B)
        self.assertEqual(android_twin["projectGeneration"], 2)
        self.assertEqual(android_twin["dialogueAct"], "unsupported")
        self.assertEqual(android_twin["expertEvidenceJson"], "[]")
        self.assertFalse(android_twin["providersEnabled"])
        self.assertEqual(android_twin["maxModelCalls"], 0)
        self.assertEqual(android_twin["providerCalls"], 0)
        self.assertEqual(android_twin["modelCalls"], 0)
        self.assertEqual(
            [message.content for message in reopened.load_messages(conversation.id)],
            [
                "Inspect project A using Prolog, Python, and Nim.",
                "Project A language inspection is complete.",
                "Switch to project B. What about the prior result?",
                "Which project B result should I use?",
                "Use an LLM to guess what I mean.",
                _UNSUPPORTED_TEXT,
            ],
        )
        reopened_database.close()

        final_database = surface.DatabaseManager(database_path)
        final_store = surface.ConversationStore(final_database)
        final_projection = final_store.load_symbolic_projection(conversation.id)
        self.assertIsNotNone(final_projection)
        assert final_projection is not None
        final_projection.assert_pure_symbolic()
        self.assertEqual(final_projection.outcome, "unknown")
        self.assertEqual(final_projection.project_id, _PROJECT_B)
        self.assertEqual(final_projection.dialogue_act, "unsupported")
        self.assertEqual(final_projection.expert_evidence, [])
        self.assertEqual(final_projection.provider_calls, 0)
        self.assertEqual(final_projection.model_calls, 0)
        final_database.close()


if __name__ == "__main__":
    unittest.main()
