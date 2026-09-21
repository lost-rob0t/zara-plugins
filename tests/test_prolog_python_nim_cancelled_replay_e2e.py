"""Gate cancelled Prolog/Python/Nim delegation through durable symbolic replay."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests import test_prolog_python_nim_inflight_cancellation_e2e as cancellation
from tests import test_prolog_python_nim_surface_parity_e2e as surface


DOTFILES_ROOT = os.environ.get("ZARA_DOTFILES_ROOT")
ZARA_CORE_ROOT = os.environ.get("ZARA_CORE_ROOT")
EXPECTED_DOTFILES_COMMIT = "3309c54ecb5f65c29374de6c60d2135a9ea2f94b"
EXPECTED_ZARA_CORE_COMMIT = "970a4ea15ee2946c52ef2a486631d73cc6c450df"
_PROJECT = "workspace:prolog-python-nim:cancelled-replay"
_SYMBOLIC_RENDERER = "symbolic-dcg/v1"
_PROVIDER_CREDENTIALS = surface._PROVIDER_CREDENTIALS


@unittest.skipUnless(
    DOTFILES_ROOT and ZARA_CORE_ROOT,
    "exact Dotfiles and Zara Core checkouts not provided",
)
class PrologPythonNimCancelledReplayE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        cls.zara_core_root = Path(ZARA_CORE_ROOT).resolve()
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for cancelled replay E2E")
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

    def _cancellation_case(self) -> cancellation.PrologPythonNimInflightCancellationE2ETests:
        case = cancellation.PrologPythonNimInflightCancellationE2ETests(
            methodName="test_nested_real_nim_cancellation_propagates_before_commit"
        )
        case.dotfiles_root = self.dotfiles_root
        case.zara_core_root = self.zara_core_root
        case.sources = self.sources
        return case

    def _surface_case(self) -> surface.PrologPythonNimSurfaceParityE2ETests:
        case = surface.PrologPythonNimSurfaceParityE2ETests(
            methodName="test_project_switch_fences_old_expert_context_on_both_surface_contracts"
        )
        case.dotfiles_root = self.dotfiles_root
        case.zara_core_root = self.zara_core_root
        case.sources = self.sources
        case.android_projection_source = self.android_projection_source
        return case

    def _cancel_real_chain(self, root: Path) -> Any:
        case = self._cancellation_case()
        backend = cancellation._BlockAfterRealNimBackend()
        _host, published, handlers = case._runtime(
            state_root=root / "language-state",
            backend=backend,
        )
        registry = cancellation.ExpertRegistry(engines=("swipl",))
        parent_handle = case._install_chain(registry, published, handlers)
        outcome, worker = case._start_parent(registry, parent_handle)

        self.assertTrue(
            backend.completed.wait(timeout=5.0),
            "real Nim backend did not complete before root cancellation",
        )
        invocation_ids = registry.snapshot().invocation_ids
        self.assertEqual(len(invocation_ids), 3)
        root_invocation_id = next(
            invocation_id
            for invocation_id in invocation_ids
            if registry.explain(invocation_id)["expert_id"] == "zara:expert/prolog"
        )
        cancel_receipt = registry.cancel(root_invocation_id)
        self.assertIs(cancel_receipt["cancelled"], True)
        self.assertIs(cancel_receipt["committed"], False)

        backend.release.set()
        worker.join(timeout=5.0)
        self.assertFalse(worker.is_alive(), "root-cancelled delegation tree did not terminate")
        self.assertNotIn("error", outcome)

        result = outcome["result"]
        self.assertIs(result.verdict, cancellation.ExpertVerdict.CANCELLED)
        self.assertEqual(result.data, {})
        self.assertEqual(result.evidence_refs, ())
        self.assertEqual(result.effect_receipts, ())
        self.assertIs(type(result.usage["model_calls"]), int)
        self.assertEqual(result.usage["model_calls"], 0)

        traces = [registry.explain(invocation_id) for invocation_id in invocation_ids]
        self.assertEqual(
            {trace["expert_id"] for trace in traces},
            {
                "zara:expert/prolog",
                "zara:expert/python",
                "zara:expert/nim",
            },
        )
        for trace in traces:
            self.assertEqual(trace["verdict"], "cancelled")
            self.assertEqual(trace["evidence_refs"], [])
            self.assertEqual(trace.get("effect_receipts", []), [])
            self.assertIs(type(trace["usage"]["model_calls"]), int)
            self.assertEqual(trace["usage"]["model_calls"], 0)
        return result

    def _assert_android_fences(self) -> None:
        source = self.android_projection_source.read_text(encoding="utf-8")
        for fragment in (
            '"stale symbolic projection write: expected generation $expectedGeneration, "',
            '"terminal turn projection is immutable"',
            'check(!providersEnabled)',
            'check(maxModelCalls == 0L)',
            'check(providerCalls == 0L && modelCalls == 0L)',
        ):
            self.assertIn(fragment, source)

    def test_cancelled_chain_restarts_without_late_evidence_or_provider_fallback(self) -> None:
        for name in _PROVIDER_CREDENTIALS:
            self.assertNotIn(name, os.environ)

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        cancelled_result = self._cancel_real_chain(root)
        self._assert_android_fences()
        surface_case = self._surface_case()

        database_path = root / "conversation.db"
        database = surface.DatabaseManager(database_path)
        store = surface.ConversationStore(database)
        conversation = store.create_conversation(
            "Cancelled typed language replay",
            conversation_id="conversation:prolog-python-nim-cancelled-replay",
        )
        store.save_message(
            surface_case._message(
                conversation.id,
                1,
                "turn:cancelled-inspect",
                surface.MessageRole.USER,
                "Inspect this project with Prolog, Python, and Nim.",
            )
        )

        pending = store.save_symbolic_projection(
            surface.SymbolicConversationProjection(
                conversation_id=conversation.id,
                projection_generation=1,
                runtime_generation=1,
                turn_id="turn:cancelled-inspect",
                outcome="pending",
                project_id=_PROJECT,
                project_generation=1,
                dialogue_act="expert.pending",
                dialogue_state={
                    "active_project": _PROJECT,
                    "selected_experts": [
                        "zara:expert/prolog",
                        "zara:expert/python",
                        "zara:expert/nim",
                    ],
                },
                expert_evidence=[],
                renderer_provenance="",
                providers_enabled=False,
                max_model_calls=0,
                provider_calls=0,
                model_calls=0,
            ),
            expected_generation=0,
        )
        pending.assert_pure_symbolic()

        cancelled = store.save_symbolic_projection(
            surface.SymbolicConversationProjection(
                conversation_id=conversation.id,
                projection_generation=2,
                runtime_generation=1,
                turn_id="turn:cancelled-inspect",
                outcome="cancelled",
                project_id=_PROJECT,
                project_generation=1,
                dialogue_act="cancelled",
                dialogue_state={
                    "active_project": _PROJECT,
                    "cancelled_expert_tree": True,
                },
                expert_evidence=[],
                renderer_provenance="",
                providers_enabled=False,
                max_model_calls=0,
                provider_calls=0,
                model_calls=cancelled_result.usage["model_calls"],
            ),
            expected_generation=pending.projection_generation,
        )
        cancelled.assert_pure_symbolic()
        store.save_message(
            surface_case._message(
                conversation.id,
                2,
                "turn:cancelled-inspect",
                surface.MessageRole.ASSISTANT,
                "Cancelled before any expert result was committed.",
            )
        )

        late_evidence = [
            {
                "expert_id": "zara:expert/nim",
                "evidence_refs": ["late-evidence-must-not-commit"],
                "verdict": "succeeded",
                "model_calls": 0,
            }
        ]
        with self.assertRaisesRegex(RuntimeError, "stale symbolic projection write"):
            store.save_symbolic_projection(
                surface.SymbolicConversationProjection(
                    conversation_id=conversation.id,
                    projection_generation=2,
                    runtime_generation=1,
                    turn_id="turn:cancelled-inspect",
                    outcome="success",
                    project_id=_PROJECT,
                    project_generation=1,
                    dialogue_act="expert.answer",
                    expert_evidence=late_evidence,
                    renderer_provenance=_SYMBOLIC_RENDERER,
                    providers_enabled=False,
                    max_model_calls=0,
                    provider_calls=0,
                    model_calls=0,
                ),
                expected_generation=pending.projection_generation,
            )

        with self.assertRaisesRegex(RuntimeError, "terminal turn projection is immutable"):
            store.save_symbolic_projection(
                surface.SymbolicConversationProjection(
                    conversation_id=conversation.id,
                    projection_generation=3,
                    runtime_generation=1,
                    turn_id="turn:cancelled-inspect",
                    outcome="success",
                    project_id=_PROJECT,
                    project_generation=1,
                    dialogue_act="expert.answer",
                    expert_evidence=late_evidence,
                    renderer_provenance=_SYMBOLIC_RENDERER,
                    providers_enabled=False,
                    max_model_calls=0,
                    provider_calls=0,
                    model_calls=0,
                ),
                expected_generation=cancelled.projection_generation,
            )
        database.close()

        reopened_database = surface.DatabaseManager(database_path)
        reopened = surface.ConversationStore(reopened_database)
        recovered = reopened.load_symbolic_projection(conversation.id)
        self.assertIsNotNone(recovered)
        assert recovered is not None
        recovered.assert_pure_symbolic()
        self.assertEqual(recovered.outcome, "cancelled")
        self.assertEqual(recovered.dialogue_act, "cancelled")
        self.assertEqual(recovered.expert_evidence, [])
        self.assertIs(recovered.providers_enabled, False)
        self.assertEqual(recovered.max_model_calls, 0)
        self.assertEqual(recovered.provider_calls, 0)
        self.assertEqual(recovered.model_calls, 0)

        from zara import __main__ as zara_cli
        from zara.desktop.conversation.replay_status import conversation_symbolic_status

        replay = zara_cli._conversation_replay_payload(reopened, conversation.id)
        status = conversation_symbolic_status(reopened, conversation.id)
        projection = replay["symbolic_projection"]
        self.assertIsNotNone(projection)
        assert projection is not None
        self.assertEqual(replay["version"], "ZARA-CONVERSATION-REPLAY/1")
        self.assertEqual(status["version"], "ZARA-SYMBOLIC-REPLAY/1")
        self.assertEqual(status["symbolic_projection"], projection)
        self.assertEqual(projection["outcome"], "cancelled")
        self.assertEqual(projection["dialogue_act"], "cancelled")
        self.assertEqual(projection["expert_evidence"], [])
        self.assertIs(projection["providers_enabled"], False)
        self.assertEqual(projection["max_model_calls"], 0)
        self.assertEqual(projection["provider_calls"], 0)
        self.assertEqual(projection["model_calls"], 0)
        self.assertEqual(
            [message["content"] for message in replay["messages"]],
            [
                "Inspect this project with Prolog, Python, and Nim.",
                "Cancelled before any expert result was committed.",
            ],
        )

        android = surface._android_twin(recovered)
        self.assertEqual(json.loads(android["expertEvidenceJson"]), [])
        self.assertEqual(android["outcome"], projection["outcome"])
        self.assertEqual(android["dialogueAct"], projection["dialogue_act"])
        self.assertIs(android["providersEnabled"], False)
        self.assertEqual(android["maxModelCalls"], 0)
        self.assertEqual(android["providerCalls"], 0)
        self.assertEqual(android["modelCalls"], 0)
        reopened_database.close()


if __name__ == "__main__":
    unittest.main()
