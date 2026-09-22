"""Gate Nix/Bash cancellation across durable pure-symbolic conversation restart."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

from tests import test_nix_bash_current_core_delegation_e2e as current_core


DOTFILES_ROOT = os.environ.get("ZARA_DOTFILES_ROOT")
ZARA_CURRENT_CORE_ROOT = os.environ.get("ZARA_CURRENT_CORE_ROOT")
EXPECTED_DOTFILES_COMMIT = "1b93e01f3482e49a853f651eb28c21eb1d9cad0e"
EXPECTED_ZARA_CORE_COMMIT = "4a7ad7673910e901a09a9e79c81e60bd2aeed8aa"
PROJECT_ID = "workspace:nix-bash:cancelled-restart"
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
    from zara.experts import (  # noqa: E402
        ExpertDescriptor,
        ExpertLimits,
        ExpertRegistry,
        ExpertVerdict,
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
class NixBashCancelledRestartE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        cls.zara_core_root = Path(ZARA_CURRENT_CORE_ROOT).resolve()
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for Nix/Bash cancelled restart E2E")
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
        for source_files in cls.sources.values():
            for source in source_files:
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

    def _assert_android_fences(self) -> None:
        source = self.android_projection_source.read_text(encoding="utf-8")
        for fragment in (
            '"stale symbolic projection write: expected generation $expectedGeneration, "',
            '"terminal turn projection is immutable"',
            "fun assertPureSymbolic()",
            '"pure-symbolic conversation has providers enabled"',
        ):
            self.assertIn(fragment, source)

    def _cancel_real_expert(
        self,
        expert_id: str,
        source: str,
        state_root: Path,
    ) -> Any:
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
        descriptor = ExpertDescriptor.from_wire(published[expert_id])
        real_handler = current_core.make_language_expert_handler(host, expert_id)
        started = threading.Event()
        release = threading.Event()
        calls: list[tuple[str, dict[str, Any]]] = []

        def blocking_handler(*, expert_operation: str, **payload: Any) -> dict[str, Any]:
            calls.append((expert_operation, dict(payload)))
            started.set()
            if not release.wait(timeout=10.0):
                raise RuntimeError("cancelled-restart test release timed out")
            return dict(real_handler(expert_operation=expert_operation, **payload))

        registry = ExpertRegistry(engines=("swipl",))
        registry.register(descriptor, blocking_handler)
        handle, receipt = registry.activate(
            "user:nix-bash-cancelled-restart",
            PROJECT_ID,
            expert_id,
            expected_registry_generation=registry.generation,
            expected_runtime_generation=registry.runtime_generation,
        )
        self.assertEqual(receipt["state"], "active")
        language = expert_id.rsplit("/", 1)[-1]
        outcome: dict[str, Any] = {}

        def invoke() -> None:
            try:
                outcome["result"] = registry.invoke(
                    handle,
                    "inspect",
                    {
                        "source": source,
                        "source_generation": "generation:nix-bash:cancelled-restart:1",
                    },
                    limits=ExpertLimits(max_model_calls=0),
                    request_id=f"req:nix-bash:cancelled-restart:{language}",
                    idempotency_key=f"idem:nix-bash:cancelled-restart:{language}",
                )
            except BaseException as error:  # noqa: BLE001
                outcome["error"] = error

        worker = threading.Thread(target=invoke, daemon=True)
        worker.start()
        self.assertTrue(
            started.wait(timeout=5.0),
            f"Core never dispatched the real {language} brain",
        )
        invocation_ids = registry.snapshot().invocation_ids
        self.assertEqual(len(invocation_ids), 1)
        cancel_receipt = registry.cancel(invocation_ids[0])
        self.assertIs(cancel_receipt["cancelled"], True)
        self.assertIs(cancel_receipt["committed"], False)
        release.set()
        worker.join(timeout=10.0)
        self.assertFalse(worker.is_alive(), f"cancelled {language} invocation did not terminate")
        self.assertNotIn("error", outcome)

        result = outcome["result"]
        self.assertIs(result.verdict, ExpertVerdict.CANCELLED)
        self.assertEqual(result.data, {})
        self.assertEqual(result.evidence_refs, ())
        self.assertEqual(result.effect_receipts, ())
        self.assertEqual(result.usage, {"model_calls": 0})
        self.assertIs(result.replayed, False)
        self.assertEqual(len(calls), 1)
        trace = registry.explain(result.invocation_id)
        self.assertEqual(trace["verdict"], "cancelled")
        self.assertEqual(trace["evidence_refs"], [])
        self.assertEqual(trace.get("effect_receipts", []), [])
        self.assertEqual(trace["usage"], {"model_calls": 0})
        return result

    def test_cancelled_real_brains_survive_restart_without_late_output_or_fallback(self) -> None:
        for name in PROVIDER_CREDENTIALS:
            self.assertNotIn(name, os.environ)
        self._assert_android_fences()

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        cancelled_results = {
            "zara:expert/nix": self._cancel_real_expert(
                "zara:expert/nix",
                "{ x = 1; }",
                root / "nix-state",
            ),
            "zara:expert/bash": self._cancel_real_expert(
                "zara:expert/bash",
                "printf '%s\\n' ok",
                root / "bash-state",
            ),
        }
        self.assertEqual(
            {result.usage["model_calls"] for result in cancelled_results.values()},
            {0},
        )

        database_path = root / "conversation.db"
        database = DatabaseManager(database_path)
        store = ConversationStore(database)
        record = store.create_conversation(
            "Nix Bash cancelled restart",
            conversation_id="conversation:nix-bash:cancelled-restart",
        )
        pending = store.save_symbolic_projection(
            SymbolicConversationProjection(
                conversation_id=record.id,
                projection_generation=1,
                runtime_generation=1,
                turn_id="turn:nix-bash:cancelled-restart",
                outcome="pending",
                project_id=PROJECT_ID,
                project_generation=1,
                dialogue_act="expert.pending",
                dialogue_state={
                    "active_project": PROJECT_ID,
                    "selected_experts": ["zara:expert/nix", "zara:expert/bash"],
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
            SymbolicConversationProjection(
                conversation_id=record.id,
                projection_generation=2,
                runtime_generation=1,
                turn_id="turn:nix-bash:cancelled-restart",
                outcome="cancelled",
                project_id=PROJECT_ID,
                project_generation=1,
                dialogue_act="cancelled",
                dialogue_state={
                    "active_project": PROJECT_ID,
                    "cancelled_experts": sorted(cancelled_results),
                },
                expert_evidence=[],
                renderer_provenance="",
                providers_enabled=False,
                max_model_calls=0,
                provider_calls=0,
                model_calls=0,
            ),
            expected_generation=pending.projection_generation,
        )
        cancelled.assert_pure_symbolic()

        late_evidence = [
            {
                "expert_id": "zara:expert/nix",
                "verdict": "succeeded",
                "evidence_refs": ["late-evidence-must-not-commit"],
                "model_calls": 0,
            }
        ]
        with self.assertRaisesRegex(RuntimeError, "stale symbolic projection write"):
            store.save_symbolic_projection(
                SymbolicConversationProjection(
                    conversation_id=record.id,
                    projection_generation=2,
                    runtime_generation=2,
                    turn_id="turn:nix-bash:late-stale",
                    outcome="success",
                    project_id=PROJECT_ID,
                    project_generation=1,
                    dialogue_act="expert.answer",
                    expert_evidence=late_evidence,
                    renderer_provenance="symbolic-dcg/v1",
                    providers_enabled=False,
                    max_model_calls=0,
                    provider_calls=0,
                    model_calls=0,
                ),
                expected_generation=pending.projection_generation,
            )
        with self.assertRaisesRegex(RuntimeError, "terminal turn projection is immutable"):
            store.save_symbolic_projection(
                SymbolicConversationProjection(
                    conversation_id=record.id,
                    projection_generation=3,
                    runtime_generation=1,
                    turn_id="turn:nix-bash:cancelled-restart",
                    outcome="success",
                    project_id=PROJECT_ID,
                    project_generation=1,
                    dialogue_act="expert.answer",
                    expert_evidence=late_evidence,
                    renderer_provenance="symbolic-dcg/v1",
                    providers_enabled=False,
                    max_model_calls=0,
                    provider_calls=0,
                    model_calls=0,
                ),
                expected_generation=cancelled.projection_generation,
            )
        database.close()

        reopened_database = DatabaseManager(database_path)
        reopened = ConversationStore(reopened_database)
        recovered = reopened.load_symbolic_projection(record.id)
        self.assertIsNotNone(recovered)
        assert recovered is not None
        recovered.assert_pure_symbolic()
        self.assertEqual(recovered.outcome, "cancelled")
        self.assertEqual(recovered.dialogue_act, "cancelled")
        self.assertEqual(recovered.expert_evidence, [])
        self.assertEqual(
            recovered.dialogue_state["cancelled_experts"],
            ["zara:expert/bash", "zara:expert/nix"],
        )
        self.assertIs(recovered.providers_enabled, False)
        self.assertEqual(recovered.max_model_calls, 0)
        self.assertEqual(recovered.provider_calls, 0)
        self.assertEqual(recovered.model_calls, 0)

        android = _android_twin(recovered)
        self.assertEqual(android["outcome"], "cancelled")
        self.assertEqual(android["dialogueAct"], "cancelled")
        self.assertEqual(json.loads(android["expertEvidenceJson"]), [])
        self.assertIs(android["providersEnabled"], False)
        self.assertEqual(android["maxModelCalls"], 0)
        self.assertEqual(android["providerCalls"], 0)
        self.assertEqual(android["modelCalls"], 0)
        reopened_database.close()


if __name__ == "__main__":
    unittest.main()
