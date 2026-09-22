"""Persist real Nix/Bash symbolic evidence through Zara conversation restart."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests import test_nix_bash_current_core_delegation_e2e as current_core


DOTFILES_ROOT = os.environ.get("ZARA_DOTFILES_ROOT")
ZARA_CURRENT_CORE_ROOT = os.environ.get("ZARA_CURRENT_CORE_ROOT")
EXPECTED_DOTFILES_COMMIT = "1b93e01f3482e49a853f651eb28c21eb1d9cad0e"
EXPECTED_ZARA_CORE_COMMIT = "4a7ad7673910e901a09a9e79c81e60bd2aeed8aa"
PROJECT_ID = "workspace:nix-bash:durable-persistence"
SYMBOLIC_RENDERER = "symbolic-dcg/v1"
PROVIDER_CREDENTIALS = (
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

if ZARA_CURRENT_CORE_ROOT:
    sys.path.insert(0, str(Path(ZARA_CURRENT_CORE_ROOT).resolve()))
    from zara.database import DatabaseManager  # noqa: E402
    from zara.desktop.conversation import (  # noqa: E402
        ConversationStore,
        SymbolicConversationProjection,
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _android_twin(projection: Any) -> dict[str, Any]:
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
        "expertEvidenceJson": _canonical_json(projection.expert_evidence),
        "rendererProvenance": projection.renderer_provenance,
        "providersEnabled": projection.providers_enabled,
        "maxModelCalls": projection.max_model_calls,
        "providerCalls": projection.provider_calls,
        "modelCalls": projection.model_calls,
    }


@unittest.skipUnless(
    DOTFILES_ROOT and ZARA_CURRENT_CORE_ROOT,
    "exact Dotfiles and current Zara Core checkouts not provided",
)
class NixBashDurablePersistenceE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        cls.zara_core_root = Path(ZARA_CURRENT_CORE_ROOT).resolve()
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for durable persistence E2E")
        current_core._checkout_head(
            cls.dotfiles_root,
            EXPECTED_DOTFILES_COMMIT,
            "Dotfiles producer",
        )
        current_core._checkout_head(
            cls.zara_core_root,
            EXPECTED_ZARA_CORE_COMMIT,
            "Zara Core",
        )
        cls.sources = {
            language: [
                cls.dotfiles_root
                / ".zara"
                / "experts"
                / language
                / "kb"
                / "expert.pl"
            ]
            for language in ("nix", "bash")
        }
        for paths in cls.sources.values():
            for source in paths:
                if not source.is_file():
                    raise AssertionError(f"missing canonical expert source: {source}")
        current_core.validate_language_source_contracts(cls.sources)
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

    def _assert_android_contract(self) -> None:
        source = self.android_projection_source.read_text(encoding="utf-8")
        for fragment in (
            'val expertEvidenceJson: String = "[]"',
            "val providersEnabled: Boolean = true",
            "val maxModelCalls: Long = 1",
            "val providerCalls: Long = 0",
            "val modelCalls: Long = 0",
            "fun assertPureSymbolic()",
            '"pure-symbolic conversation has providers enabled"',
            '"successful projection requires canonical symbolic renderer"',
        ):
            self.assertIn(fragment, source)

    def _real_evidence(self, state_root: Path) -> list[dict[str, Any]]:
        host = current_core.ExpertHost(
            current_core.SwiplBackend(),
            state_root=state_root,
        )
        registered = current_core.register_language_family(host, self.sources)
        self.assertEqual(registered, frozenset({"nix", "bash"}))
        published = {
            item["expert_id"]: item
            for item in current_core.descriptors(registered)
        }
        cases = (
            ("zara:expert/nix", "{ x = 1; }"),
            ("zara:expert/bash", "printf '%s\\n' ok"),
        )
        evidence: list[dict[str, Any]] = []
        for expert_id, source in cases:
            descriptor = current_core.ExpertDescriptor.from_wire(published[expert_id])
            registry = current_core.ExpertRegistry(engines=("swipl",))
            registry.register(
                descriptor,
                current_core.make_language_expert_handler(host, expert_id),
            )
            handle, receipt = registry.activate(
                "user:nix-bash-persistence",
                PROJECT_ID,
                expert_id,
                expected_registry_generation=registry.generation,
                expected_runtime_generation=registry.runtime_generation,
            )
            self.assertEqual(receipt["state"], "active")
            language = expert_id.rsplit("/", 1)[-1]
            result = registry.invoke(
                handle,
                "inspect",
                {
                    "source": source,
                    "source_generation": "generation:nix-bash:persistence:1",
                },
                limits=current_core.ExpertLimits(max_model_calls=0),
                request_id=f"req:nix-bash:persistence:{language}",
            )
            self.assertIs(result.verdict, current_core.ExpertVerdict.SUCCEEDED)
            self.assertEqual(result.usage, {"model_calls": 0})
            self.assertEqual(result.effect_receipts, ())
            self.assertTrue(result.evidence_refs)
            evidence.append(
                {
                    "expert_id": expert_id,
                    "operation": "inspect",
                    "verdict": result.verdict.value,
                    "invocation_id": result.invocation_id,
                    "data": result.data,
                    "evidence_refs": list(result.evidence_refs),
                    "model_calls": result.usage["model_calls"],
                    "effect_receipts": list(result.effect_receipts),
                }
            )
        evidence.sort(key=lambda item: item["expert_id"])
        return json.loads(_canonical_json(evidence))

    def test_real_evidence_survives_restart_followup_and_stale_write_fence(self) -> None:
        for name in PROVIDER_CREDENTIALS:
            self.assertNotIn(name, os.environ)
        self._assert_android_contract()

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        expert_evidence = self._real_evidence(root / "expert-state")

        database_path = root / "conversation.db"
        database = DatabaseManager(database_path)
        store = ConversationStore(database)
        record = store.create_conversation(
            "Nix Bash pure-symbolic persistence",
            conversation_id="conversation:nix-bash:durable-persistence",
        )
        first = store.save_symbolic_projection(
            SymbolicConversationProjection(
                conversation_id=record.id,
                projection_generation=1,
                runtime_generation=1,
                turn_id="turn:nix-bash:inspect",
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
        first.assert_pure_symbolic()
        database.close()

        reopened_database = DatabaseManager(database_path)
        reopened = ConversationStore(reopened_database)
        recovered = reopened.load_symbolic_projection(record.id)
        self.assertIsNotNone(recovered)
        assert recovered is not None
        recovered.assert_pure_symbolic()
        self.assertEqual(recovered.expert_evidence, expert_evidence)
        self.assertEqual(recovered.dialogue_state["followups"], ["why", "show evidence"])

        android = _android_twin(recovered)
        self.assertEqual(json.loads(android["expertEvidenceJson"]), expert_evidence)
        self.assertIs(android["providersEnabled"], False)
        self.assertEqual(android["maxModelCalls"], 0)
        self.assertEqual(android["providerCalls"], 0)
        self.assertEqual(android["modelCalls"], 0)

        followup = reopened.save_symbolic_projection(
            SymbolicConversationProjection(
                conversation_id=record.id,
                projection_generation=2,
                runtime_generation=2,
                turn_id="turn:nix-bash:why",
                outcome="success",
                project_id=PROJECT_ID,
                project_generation=1,
                dialogue_act="expert.followup",
                dialogue_state={
                    "active_project": PROJECT_ID,
                    "resolved_followup": "why",
                    "source_turn": recovered.turn_id,
                },
                expert_evidence=recovered.expert_evidence,
                renderer_provenance=SYMBOLIC_RENDERER,
                providers_enabled=False,
                max_model_calls=0,
                provider_calls=0,
                model_calls=0,
            ),
            expected_generation=recovered.projection_generation,
        )
        followup.assert_pure_symbolic()
        self.assertEqual(followup.expert_evidence, expert_evidence)

        with self.assertRaisesRegex(RuntimeError, "stale symbolic projection write"):
            reopened.save_symbolic_projection(
                SymbolicConversationProjection(
                    conversation_id=record.id,
                    projection_generation=3,
                    runtime_generation=3,
                    turn_id="turn:nix-bash:late",
                    outcome="success",
                    project_id=PROJECT_ID,
                    project_generation=1,
                    dialogue_act="expert.answer",
                    dialogue_state={"late": True},
                    expert_evidence=expert_evidence,
                    renderer_provenance=SYMBOLIC_RENDERER,
                    providers_enabled=False,
                    max_model_calls=0,
                    provider_calls=0,
                    model_calls=0,
                ),
                expected_generation=recovered.projection_generation,
            )

        current = reopened.load_symbolic_projection(record.id)
        self.assertIsNotNone(current)
        assert current is not None
        current.assert_pure_symbolic()
        self.assertEqual(current.projection_generation, followup.projection_generation)
        self.assertEqual(current.turn_id, "turn:nix-bash:why")
        self.assertEqual(current.expert_evidence, expert_evidence)
        self.assertEqual(current.provider_calls, 0)
        self.assertEqual(current.model_calls, 0)
        reopened_database.close()


if __name__ == "__main__":
    unittest.main()
