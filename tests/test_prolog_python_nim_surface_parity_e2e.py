"""Gate Prolog/Python/Nim conversation state across Desktop/Android semantics."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DOTFILES_ROOT = os.environ.get("ZARA_DOTFILES_ROOT")
ZARA_CORE_ROOT = os.environ.get("ZARA_CORE_ROOT")
EXPECTED_DOTFILES_COMMIT = "20e16c4fb084df4b01a17c06cd0e11ef5df2fb62"
EXPECTED_ZARA_CORE_COMMIT = "dc74a41b216388662e55412e1e09a1c8c2fad5a7"
ZARA_EXPERT_LIB = REPO_ROOT / "plugins" / "zara-expert" / "lib"

if ZARA_CORE_ROOT:
    sys.path.insert(0, str(Path(ZARA_CORE_ROOT).resolve()))
sys.path.insert(0, str(ZARA_EXPERT_LIB))

from zara_expert.backend import SwiplBackend
from zara_expert.domain import ExpertHost
from zara_expert.language_family import descriptors, register_language_family
from zara_expert.language_handler import make_language_expert_handler
from zara_expert.language_source_contract import validate_language_source_contracts

if ZARA_CORE_ROOT:
    from zara.principals import PrincipalContext

    server_facade = types.ModuleType("zara.server")
    server_facade.PrincipalContext = PrincipalContext
    sys.modules["zara.server"] = server_facade

    from zara.database import DatabaseManager
    from zara.desktop.conversation import ConversationStore, SymbolicConversationProjection
    from zara.desktop.conversation.models import MessageRecord, MessageRole, MessageStatus
    from zara.experts import ExpertDescriptor, ExpertLimits, ExpertRegistry, ExpertVerdict


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
_PROJECT_A = "workspace:prolog-python-nim:A"
_PROJECT_B = "workspace:prolog-python-nim:B"
_SYMBOLIC_RENDERER = "symbolic-dcg/v1"


def _run(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _checkout_head(root: Path, expected: str, label: str) -> None:
    result = _run("git", "rev-parse", "HEAD", cwd=root)
    if result.returncode != 0:
        raise AssertionError(f"cannot resolve {label} checkout: {result.stderr}")
    actual = result.stdout.strip()
    if actual != expected:
        raise AssertionError(
            f"{label} checkout must be exact: expected {expected}, got {actual}"
        )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _android_twin(projection: Any) -> dict[str, Any]:
    """Project the canonical persisted state onto Android's public field names."""
    return {
        "conversationId": projection.conversation_id,
        "projectionGeneration": projection.projection_generation,
        "runtimeGeneration": projection.runtime_generation,
        "turnId": projection.turn_id,
        "outcome": projection.outcome,
        "projectId": projection.project_id,
        "projectGeneration": projection.project_generation,
        "dialogueAct": projection.dialogue_act,
        "dialogueStateJson": _canonical_json(projection.dialogue_state),
        "discourseEntitiesJson": _canonical_json(projection.discourse_entities),
        "unresolvedQuestionsJson": _canonical_json(projection.unresolved_questions),
        "expertEvidenceJson": _canonical_json(projection.expert_evidence),
        "verifiedFactsJson": _canonical_json(projection.verified_facts),
        "verifiedOutcomeRefs": list(projection.verified_outcome_refs),
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
class PrologPythonNimSurfaceParityE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        cls.zara_core_root = Path(ZARA_CORE_ROOT).resolve()
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for surface parity E2E")
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

    def _runtime(self, state_root: Path):
        validate_language_source_contracts(self.sources)
        host = ExpertHost(SwiplBackend(), state_root=state_root)
        registered = register_language_family(host, self.sources)
        self.assertEqual(registered, frozenset({"prolog", "python", "nim"}))
        published = {item["expert_id"]: item for item in descriptors(registered)}
        handlers = {
            expert_id: make_language_expert_handler(host, expert_id)
            for expert_id in (
                "zara:expert/prolog",
                "zara:expert/python",
                "zara:expert/nim",
            )
        }
        return published, handlers

    @staticmethod
    def _activate(registry: Any, expert_id: str, workspace: str):
        handle, receipt = registry.activate(
            "expert-builder-3",
            workspace,
            expert_id,
            expected_registry_generation=registry.generation,
            expected_runtime_generation=registry.runtime_generation,
        )
        if receipt["state"] != "active":
            raise AssertionError(f"failed to activate {expert_id}: {receipt!r}")
        return handle

    @staticmethod
    def _message(
        conversation_id: str,
        sequence: int,
        turn_id: str,
        role: Any,
        content: str,
    ) -> Any:
        timestamp = f"2026-09-21T03:00:{sequence:02d}.000000"
        return MessageRecord(
            id=f"surface-message-{sequence}",
            conversation_id=conversation_id,
            sequence=sequence,
            turn_id=turn_id,
            role=role,
            content=content,
            status=MessageStatus.COMPLETE,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _real_chain(self, state_root: Path) -> list[dict[str, Any]]:
        published, handlers = self._runtime(state_root)
        registry = ExpertRegistry(engines=("swipl",))
        handles: dict[str, Any] = {}
        child_results: dict[str, Any] = {}
        prolog_handler = handlers["zara:expert/prolog"]
        python_handler = handlers["zara:expert/python"]

        def delegating_python(*, expert_operation: str, **payload: Any) -> dict[str, Any]:
            result = python_handler(expert_operation=expert_operation, **payload)
            child_results["nim"] = registry.invoke(
                handles["zara:expert/nim"],
                "inspect",
                {
                    "source": "proc projectA(): int = 42\n",
                    "source_generation": "surface-nim-A-1",
                },
                limits=ExpertLimits(max_model_calls=64),
            )
            return result

        def delegating_prolog(*, expert_operation: str, **payload: Any) -> dict[str, Any]:
            result = prolog_handler(expert_operation=expert_operation, **payload)
            child_results["python"] = registry.invoke(
                handles["zara:expert/python"],
                "inspect",
                {
                    "source": "def project_a():\n    return 42\n",
                    "source_generation": "surface-python-A-1",
                },
                limits=ExpertLimits(max_model_calls=64),
            )
            return result

        for expert_id in (
            "zara:expert/prolog",
            "zara:expert/python",
            "zara:expert/nim",
        ):
            handler = handlers[expert_id]
            if expert_id == "zara:expert/prolog":
                handler = delegating_prolog
            elif expert_id == "zara:expert/python":
                handler = delegating_python
            registry.register(ExpertDescriptor.from_wire(published[expert_id]), handler)

        for expert_id in (
            "zara:expert/prolog",
            "zara:expert/python",
            "zara:expert/nim",
        ):
            handles[expert_id] = self._activate(registry, expert_id, _PROJECT_A)

        root_result = registry.invoke(
            handles["zara:expert/prolog"],
            "inspect",
            {
                "source": "project_fact(project_a, ready).",
                "source_generation": "surface-prolog-A-1",
            },
            limits=ExpertLimits(max_model_calls=0),
        )
        for result in (root_result, child_results["python"], child_results["nim"]):
            self.assertIs(result.verdict, ExpertVerdict.SUCCEEDED)
            self.assertTrue(result.evidence_refs)
            self.assertEqual(result.effect_receipts, ())
            self.assertIs(type(result.usage["model_calls"]), int)
            self.assertEqual(result.usage["model_calls"], 0)

        traces = [
            registry.explain(invocation_id)
            for invocation_id in registry.snapshot().invocation_ids
        ]
        self.assertEqual(len(traces), 3)
        evidence = []
        for trace in traces:
            self.assertEqual(trace["verdict"], "succeeded")
            self.assertTrue(trace["evidence_refs"])
            self.assertEqual(trace.get("effect_receipts", []), [])
            self.assertIs(type(trace["usage"]["model_calls"]), int)
            self.assertEqual(trace["usage"]["model_calls"], 0)
            evidence.append(
                {
                    "expert_id": trace["expert_id"],
                    "invocation_id": trace["invocation_id"],
                    "evidence_refs": list(trace["evidence_refs"]),
                    "verdict": trace["verdict"],
                    "model_calls": trace["usage"]["model_calls"],
                }
            )
        return sorted(evidence, key=lambda item: item["expert_id"])

    def _assert_android_contract_tracks_desktop_rules(self) -> None:
        source = self.android_projection_source.read_text(encoding="utf-8")
        required_fragments = (
            'val projectId: String? = null',
            'val projectGeneration: Long = 0',
            'val dialogueStateJson: String = "{}"',
            'val expertEvidenceJson: String = "[]"',
            'val providersEnabled: Boolean = true',
            'val maxModelCalls: Long = 1',
            'val providerCalls: Long = 0',
            'val modelCalls: Long = 0',
            '"project switch must advance projectGeneration"',
            '"provider policy widening rejected"',
            '"model-call budget widening rejected"',
            '"desktop_symbolic_projections"',
        )
        for fragment in required_fragments:
            self.assertIn(fragment, source)

    def test_project_switch_fences_old_expert_context_on_both_surface_contracts(self) -> None:
        for name in _PROVIDER_CREDENTIALS:
            self.assertNotIn(name, os.environ)

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        expert_evidence = self._real_chain(root / "expert-state")
        self._assert_android_contract_tracks_desktop_rules()

        database_path = root / "conversation.db"
        database = DatabaseManager(database_path)
        store = ConversationStore(database)
        conversation = store.create_conversation(
            "Surface parity project switch",
            conversation_id="conversation:surface-parity",
        )
        store.save_message(
            self._message(
                conversation.id,
                1,
                "turn:project-a",
                MessageRole.USER,
                "Inspect project A using Prolog, Python, and Nim.",
            )
        )
        store.save_message(
            self._message(
                conversation.id,
                2,
                "turn:project-a",
                MessageRole.ASSISTANT,
                "Project A language inspection is complete.",
            )
        )
        project_a = store.save_symbolic_projection(
            SymbolicConversationProjection(
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

        reopened_database = DatabaseManager(database_path)
        reopened = ConversationStore(reopened_database)
        recovered_a = reopened.load_symbolic_projection(conversation.id)
        self.assertIsNotNone(recovered_a)
        assert recovered_a is not None
        recovered_a.assert_pure_symbolic()
        self.assertEqual(recovered_a.expert_evidence, expert_evidence)

        reopened.save_message(
            self._message(
                conversation.id,
                3,
                "turn:project-switch",
                MessageRole.USER,
                "Switch to project B. What about the prior result?",
            )
        )
        reopened.save_message(
            self._message(
                conversation.id,
                4,
                "turn:project-switch",
                MessageRole.ASSISTANT,
                "Which project B result should I use?",
            )
        )
        project_b = reopened.save_symbolic_projection(
            SymbolicConversationProjection(
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
                renderer_provenance=_SYMBOLIC_RENDERER,
                providers_enabled=False,
                max_model_calls=0,
                provider_calls=0,
                model_calls=0,
            ),
            expected_generation=project_a.projection_generation,
        )
        project_b.assert_pure_symbolic()

        stale_project_a = SymbolicConversationProjection(
            conversation_id=conversation.id,
            projection_generation=3,
            runtime_generation=3,
            turn_id="turn:late-project-a",
            outcome="success",
            project_id=_PROJECT_A,
            project_generation=1,
            dialogue_act="expert.answer",
            dialogue_state={"active_project": _PROJECT_A, "late": True},
            expert_evidence=expert_evidence,
            renderer_provenance=_SYMBOLIC_RENDERER,
            providers_enabled=False,
            max_model_calls=0,
            provider_calls=0,
            model_calls=0,
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "project switch must advance project_generation",
        ):
            reopened.save_symbolic_projection(
                stale_project_a,
                expected_generation=project_b.projection_generation,
            )

        still_b = reopened.load_symbolic_projection(conversation.id)
        self.assertIsNotNone(still_b)
        assert still_b is not None
        still_b.assert_pure_symbolic()
        self.assertEqual(still_b.project_id, _PROJECT_B)
        self.assertEqual(still_b.project_generation, 2)
        self.assertEqual(still_b.expert_evidence, [])
        self.assertEqual(still_b.dialogue_act, "clarify")
        self.assertEqual(still_b.provider_calls, 0)
        self.assertEqual(still_b.model_calls, 0)

        android_twin = _android_twin(still_b)
        self.assertEqual(android_twin["projectId"], _PROJECT_B)
        self.assertEqual(android_twin["projectGeneration"], 2)
        self.assertEqual(android_twin["dialogueAct"], "clarify")
        self.assertEqual(android_twin["expertEvidenceJson"], "[]")
        self.assertFalse(android_twin["providersEnabled"])
        self.assertEqual(android_twin["maxModelCalls"], 0)
        self.assertEqual(android_twin["providerCalls"], 0)
        self.assertEqual(android_twin["modelCalls"], 0)
        self.assertEqual(
            json.loads(android_twin["unresolvedQuestionsJson"]),
            still_b.unresolved_questions,
        )
        reopened_database.close()

        final_database = DatabaseManager(database_path)
        final_store = ConversationStore(final_database)
        final_projection = final_store.load_symbolic_projection(conversation.id)
        self.assertIsNotNone(final_projection)
        assert final_projection is not None
        final_projection.assert_pure_symbolic()
        self.assertEqual(final_projection.project_id, _PROJECT_B)
        self.assertEqual(final_projection.expert_evidence, [])
        self.assertEqual(
            [message.content for message in final_store.load_messages(conversation.id)],
            [
                "Inspect project A using Prolog, Python, and Nim.",
                "Project A language inspection is complete.",
                "Switch to project B. What about the prior result?",
                "Which project B result should I use?",
            ],
        )
        final_database.close()


if __name__ == "__main__":
    unittest.main()
