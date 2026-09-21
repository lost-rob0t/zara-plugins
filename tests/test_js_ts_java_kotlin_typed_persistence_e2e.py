"""Persist typed JS/TS/Java/Kotlin expert evidence through Zara conversation state."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests import test_js_ts_java_kotlin_registered_host_all_operations_e2e as host_e2e
from tests import test_js_ts_java_kotlin_symbolic_conversation_e2e as conversation


DOTFILES_ROOT = os.environ.get("ZARA_DOTFILES_ROOT")
ZARA_CORE_ROOT = os.environ.get("ZARA_CURRENT_CORE_ROOT")
EXPECTED_DOTFILES_COMMIT = "3309c54ecb5f65c29374de6c60d2135a9ea2f94b"
EXPECTED_ZARA_CORE_COMMIT = "af7185ee48def384783002332262412e9674343e"
PROJECT_A = "workspace:js-ts-java-kotlin:typed:A"
PROJECT_B = "workspace:js-ts-java-kotlin:typed:B"
SYMBOLIC_RENDERER = "symbolic-dcg/v1"


def _checkout_head(root: Path, expected: str, label: str) -> None:
    result = conversation.composition._run("git", "rev-parse", "HEAD", cwd=root)
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
    DOTFILES_ROOT and ZARA_CORE_ROOT,
    "exact Dotfiles and Zara Core checkouts not provided",
)
class JsTsJavaKotlinTypedPersistenceE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for typed persistence E2E")
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        cls.zara_core_root = Path(ZARA_CORE_ROOT).resolve()
        _checkout_head(cls.dotfiles_root, EXPECTED_DOTFILES_COMMIT, "Dotfiles producer")
        _checkout_head(cls.zara_core_root, EXPECTED_ZARA_CORE_COMMIT, "Zara Core")

        conversation.CURRENT_DOTFILES = EXPECTED_DOTFILES_COMMIT
        conversation.CURRENT_ZARA_CORE = EXPECTED_ZARA_CORE_COMMIT
        conversation.composition.EXPECTED_DOTFILES_COMMIT = EXPECTED_DOTFILES_COMMIT
        conversation.composition.EXPECTED_ZARA_CORE_COMMIT = EXPECTED_ZARA_CORE_COMMIT

        cls.sources = {
            language: [
                cls.dotfiles_root
                / ".zara"
                / "experts"
                / language
                / "kb"
                / "expert.pl"
            ]
            for language in host_e2e.PACKAGES
        }
        host_e2e.validate_language_source_contracts(cls.sources)
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

    def _host(self, root: Path) -> host_e2e.ExpertHost:
        host = host_e2e.ExpertHost(
            host_e2e.SwiplBackend(),
            state_root=root / "zara-expert-state",
        )
        registered = host_e2e.register_language_family(host, self.sources)
        self.assertEqual(registered, frozenset(host_e2e.PACKAGES))
        return host

    def _typed_evidence(self, root: Path) -> list[dict[str, Any]]:
        host = self._host(root)
        evidence: list[dict[str, Any]] = []
        for language, (package, module_name, class_name) in host_e2e.PACKAGES.items():
            module = host_e2e._load_package(package, module_name)
            runtime = host_e2e.RegisteredPredicateRuntime(host, module)
            plugin = getattr(module, f"Zara{class_name}ExpertPlugin")()
            plugin.start(runtime)

            operation_results: dict[str, dict[str, Any]] = {}
            for operation in ("inspect", "style.rules", "explain"):
                result = json.loads(
                    plugin.invoke(
                        f"typed-persistence-{language}-{operation}",
                        host_e2e.ACTIVATION_ID,
                        operation,
                        host_e2e.REGISTRY_GENERATION,
                        host_e2e.RUNTIME_GENERATION,
                        json.dumps(host_e2e._payload(language, operation)),
                    )
                )
                self.assertEqual(result["verdict"], "succeeded")
                self.assertEqual(result["usage"], {"model_calls": 0})
                self.assertEqual(result["effect_receipts"], [])
                self.assertTrue(result["evidence_refs"])
                host_e2e._assert_declared_output(self, module, operation, result["data"])
                operation_results[operation] = result

            inspect = operation_results["inspect"]
            style = operation_results["style.rules"]
            explain = operation_results["explain"]
            evidence.append(
                {
                    "expert_id": module.EXPERT_ID,
                    "inspect_data": inspect["data"],
                    "style_data": style["data"],
                    "explanation": explain["data"]["explanation"],
                    "evidence_refs": list(inspect["evidence_refs"]),
                    "model_calls": 0,
                }
            )

        evidence.sort(key=lambda item: item["expert_id"])
        return evidence

    def _assert_language_boundaries(self, evidence: list[dict[str, Any]]) -> None:
        by_id = {item["expert_id"]: item for item in evidence}
        js_rules = "\n".join(
            map(str, by_id["zara:expert/javascript"]["style_data"]["style_rules"])
        )
        ts_rules = "\n".join(
            map(str, by_id["zara:expert/typescript"]["style_data"]["style_rules"])
        )
        java_rules = "\n".join(
            map(str, by_id["zara:expert/java"]["style_data"]["style_rules"])
        )
        kotlin_rules = "\n".join(
            map(str, by_id["zara:expert/kotlin"]["style_data"]["style_rules"])
        )
        self.assertIn("no_implicit_typescript_semantics", js_rules)
        self.assertIn("explicit_type_only_imports", ts_rules)
        for jvm_rules in (java_rules, kotlin_rules):
            self.assertIn("gradle_jvm_metadata_observation_only", jvm_rules)
            self.assertIn("android_metadata_observation_only", jvm_rules)
        self.assertNotIn("coroutine", java_rules)
        self.assertIn("coroutine_structure_preserved", kotlin_rules)

    def _assert_android_contract(self) -> None:
        source = self.android_projection_source.read_text(encoding="utf-8")
        for fragment in (
            'val expertEvidenceJson: String = "[]"',
            'val providersEnabled: Boolean = true',
            'val maxModelCalls: Long = 1',
            'val providerCalls: Long = 0',
            'val modelCalls: Long = 0',
            '"project switch must advance projectGeneration"',
            '"provider policy widening rejected"',
            '"model-call budget widening rejected"',
        ):
            self.assertIn(fragment, source)

    def test_typed_operation_data_survives_restart_then_is_fenced_on_project_switch(self) -> None:
        for name in conversation._PROVIDER_CREDENTIALS:
            self.assertNotIn(name, os.environ)

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        typed_evidence = self._typed_evidence(root / "expert-state")
        self._assert_language_boundaries(typed_evidence)
        self._assert_android_contract()

        database_path = root / "conversation.db"
        database = conversation.DatabaseManager(database_path)
        store = conversation.ConversationStore(database)
        record = store.create_conversation(
            "Typed JS TS Java Kotlin evidence",
            conversation_id="conversation:typed-js-ts-java-kotlin",
        )
        store.save_message(
            conversation.JsTsJavaKotlinSymbolicConversationE2ETests._message(
                record.id,
                1,
                "turn:typed-inspect",
                conversation.MessageRole.USER,
                "Inspect JavaScript, TypeScript, Java, and Kotlin and explain the result.",
            )
        )
        store.save_message(
            conversation.JsTsJavaKotlinSymbolicConversationE2ETests._message(
                record.id,
                2,
                "turn:typed-inspect",
                conversation.MessageRole.ASSISTANT,
                conversation.SUMMARY,
            )
        )
        project_a = store.save_symbolic_projection(
            conversation.SymbolicConversationProjection(
                conversation_id=record.id,
                projection_generation=1,
                runtime_generation=1,
                turn_id="turn:typed-inspect",
                outcome="success",
                project_id=PROJECT_A,
                project_generation=1,
                dialogue_act="expert.answer",
                dialogue_state={
                    "active_project": PROJECT_A,
                    "selected_experts": sorted(host_e2e.PACKAGES),
                    "typed_operation_data": True,
                },
                expert_evidence=typed_evidence,
                renderer_provenance=SYMBOLIC_RENDERER,
                providers_enabled=False,
                max_model_calls=0,
                provider_calls=0,
                model_calls=0,
            ),
            expected_generation=0,
        )
        project_a.assert_pure_symbolic()
        database.close()

        reopened_database = conversation.DatabaseManager(database_path)
        reopened = conversation.ConversationStore(reopened_database)
        recovered = reopened.load_symbolic_projection(record.id)
        self.assertIsNotNone(recovered)
        assert recovered is not None
        recovered.assert_pure_symbolic()
        self.assertEqual(recovered.expert_evidence, typed_evidence)
        self._assert_language_boundaries(recovered.expert_evidence)

        android_a = _android_twin(recovered)
        self.assertEqual(json.loads(android_a["expertEvidenceJson"]), typed_evidence)
        self.assertIs(android_a["providersEnabled"], False)
        self.assertEqual(android_a["maxModelCalls"], 0)
        self.assertEqual(android_a["providerCalls"], 0)
        self.assertEqual(android_a["modelCalls"], 0)

        root_entry = next(
            item
            for item in recovered.expert_evidence
            if item["expert_id"] == "zara:expert/javascript"
        )
        evidence_ref = root_entry["evidence_refs"][0]
        dialogue_case = conversation.JsTsJavaKotlinSymbolicConversationE2ETests(
            methodName="test_four_expert_chain_persists_and_answers_why_after_restart"
        )
        dialogue_case.zara_core_root = self.zara_core_root
        answer, why = dialogue_case._dialogue(evidence_ref)
        self.assertEqual(answer, conversation.SUMMARY)
        self.assertEqual(why, f"I answered from evidence {evidence_ref}.")

        project_b = reopened.save_symbolic_projection(
            conversation.SymbolicConversationProjection(
                conversation_id=record.id,
                projection_generation=2,
                runtime_generation=2,
                turn_id="turn:project-switch",
                outcome="success",
                project_id=PROJECT_B,
                project_generation=2,
                dialogue_act="clarify",
                dialogue_state={
                    "active_project": PROJECT_B,
                    "previous_project_evidence": "fenced",
                },
                expert_evidence=[],
                renderer_provenance=SYMBOLIC_RENDERER,
                providers_enabled=False,
                max_model_calls=0,
                provider_calls=0,
                model_calls=0,
            ),
            expected_generation=project_a.projection_generation,
        )
        project_b.assert_pure_symbolic()

        with self.assertRaisesRegex(RuntimeError, "project switch must advance"):
            reopened.save_symbolic_projection(
                conversation.SymbolicConversationProjection(
                    conversation_id=record.id,
                    projection_generation=3,
                    runtime_generation=3,
                    turn_id="turn:stale-project-a",
                    outcome="success",
                    project_id=PROJECT_A,
                    project_generation=1,
                    dialogue_act="expert.answer",
                    expert_evidence=typed_evidence,
                    renderer_provenance=SYMBOLIC_RENDERER,
                    providers_enabled=False,
                    max_model_calls=0,
                    provider_calls=0,
                    model_calls=0,
                ),
                expected_generation=project_b.projection_generation,
            )

        current = reopened.load_symbolic_projection(record.id)
        self.assertIsNotNone(current)
        assert current is not None
        current.assert_pure_symbolic()
        self.assertEqual(current.project_id, PROJECT_B)
        self.assertEqual(current.project_generation, 2)
        self.assertEqual(current.expert_evidence, [])
        android_b = _android_twin(current)
        self.assertEqual(json.loads(android_b["expertEvidenceJson"]), [])
        self.assertEqual(android_b["modelCalls"], 0)
        reopened_database.close()


if __name__ == "__main__":
    unittest.main()
