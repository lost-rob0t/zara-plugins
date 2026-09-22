"""Gate typed Prolog/Python/Nim evidence through Zara's canonical replay surface."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests import test_prolog_python_nim_surface_parity_e2e as surface
from tests import test_prolog_python_nim_typed_persistence_e2e as typed


REPO_ROOT = Path(__file__).resolve().parents[1]
DOTFILES_ROOT = os.environ.get("ZARA_DOTFILES_ROOT")
ZARA_CORE_ROOT = os.environ.get("ZARA_CORE_ROOT")
EXPECTED_DOTFILES_COMMIT = "3309c54ecb5f65c29374de6c60d2135a9ea2f94b"
EXPECTED_ZARA_CORE_COMMIT = "af7185ee48def384783002332262412e9674343e"
_PROJECT_A = "workspace:prolog-python-nim:replay:A"
_SYMBOLIC_RENDERER = "symbolic-dcg/v1"
_PROVIDER_CREDENTIALS = surface._PROVIDER_CREDENTIALS
_PROVENANCE_PREFIX = "evidence:expert-provenance:sha256:"
_PRODUCT_CASES = {
    "prolog": ("zara-prolog-expert", "zara_prolog_expert", "p(x)."),
    "python": ("zara-python-expert", "zara_python_expert", "x = 1"),
    "nim": ("zara-nim-expert", "zara_nim_expert", "let x = 1"),
}


def _load_product_adapter(language: str):
    package, module_name, _source = _PRODUCT_CASES[language]
    path = REPO_ROOT / "plugins" / package / "lib" / module_name / "plugin.py"
    spec = importlib.util.spec_from_file_location(
        f"prolog_python_nim_replay_{module_name}",
        path,
    )
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load product adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _ProductRuntime:
    def __init__(self, module, invocation_hex: str) -> None:
        self.module = module
        self.invocation_hex = invocation_hex
        self.requests: list[dict[str, object]] = []

    def resolve_capability(self, capability: str) -> str:
        if capability != "expert.invoke":
            raise AssertionError(f"unexpected product capability: {capability}")
        return capability

    def invoke_capability(self, _handle: str, request: dict[str, object]) -> dict[str, object]:
        self.requests.append(request)
        return {
            "protocol": self.module.PROTOCOL,
            "request_id": request["request_id"],
            "invocation_id": "inv:" + self.invocation_hex,
            "activation_id": request["activation_id"],
            "expert_id": self.module.EXPERT_ID,
            "expert_version": self.module.PLUGIN_VERSION,
            "manifest_digest": self.module.MANIFEST_DIGEST,
            "expert_operation": request["expert_operation"],
            "resolved_registry_generation": request["expected_registry_generation"],
            "resolved_runtime_generation": request["expected_runtime_generation"],
            "verdict": "succeeded",
            "data": {"result": {"language": self.module.LANGUAGE_BOUNDARIES["language"]}},
            "evidence_refs": [f"fixture:host:{self.module.LANGUAGE_BOUNDARIES['language']}"],
            "usage": {"model_calls": 0},
            "effect_receipts": [],
            "error_code": None,
            "error_message": "",
            "replayed": False,
        }


def _serialized_product_provenance_refs() -> dict[str, str]:
    refs: dict[str, str] = {}
    for offset, language in enumerate(("prolog", "python", "nim"), start=1):
        module = _load_product_adapter(language)
        runtime = _ProductRuntime(module, f"{offset:032x}")
        plugin = module.create_plugin()
        plugin.start(runtime)
        _package, _module_name, source = _PRODUCT_CASES[language]
        encoded = plugin.invoke(
            f"req-product-replay-{language}",
            "act:" + f"{offset:032x}",
            "inspect",
            1,
            1,
            json.dumps(
                {
                    "source": source,
                    "source_generation": f"source:product-replay:{language}:1",
                }
            ),
        )
        projected = json.loads(encoded)
        provenance = [
            ref
            for ref in projected["evidence_refs"]
            if ref.startswith(_PROVENANCE_PREFIX)
        ]
        if len(provenance) != 1:
            raise AssertionError(
                f"{module.EXPERT_ID} must serialize exactly one verified provenance ref"
            )
        if projected["usage"] != {"model_calls": 0}:
            raise AssertionError(f"{module.EXPERT_ID} widened the model ledger")
        if projected["effect_receipts"]:
            raise AssertionError(f"{module.EXPERT_ID} leaked an effect receipt")
        if runtime.requests[0]["limits"]["max_model_calls"] != 0:
            raise AssertionError(f"{module.EXPERT_ID} widened the model budget")
        refs[module.EXPERT_ID] = provenance[0]
    return refs


def _canonical_typed_evidence(
    chain_evidence: list[dict[str, Any]],
    explanations: dict[str, dict[str, Any]],
    provenance_refs: dict[str, str],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for item in chain_evidence:
        entry = dict(item)
        entry["explanation"] = explanations[entry["expert_id"]]
        if "result" in entry:
            raise AssertionError("typed replay evidence must not depend on data.result")
        if entry["model_calls"] != 0:
            raise AssertionError("typed replay evidence widened the model budget")
        if not entry["evidence_refs"]:
            raise AssertionError("typed replay evidence must retain canonical evidence refs")
        provenance_ref = provenance_refs[entry["expert_id"]]
        if provenance_ref in entry["evidence_refs"]:
            raise AssertionError("host evidence already contains product provenance identity")
        entry["evidence_refs"] = [*entry["evidence_refs"], provenance_ref]
        evidence.append(entry)
    return sorted(evidence, key=lambda item: item["expert_id"])


@unittest.skipUnless(
    DOTFILES_ROOT and ZARA_CORE_ROOT,
    "exact Dotfiles and Zara Core checkouts not provided",
)
class PrologPythonNimReplayContractE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        cls.zara_core_root = Path(ZARA_CORE_ROOT).resolve()
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for canonical replay E2E")
        typed._checkout_head(
            cls.dotfiles_root,
            EXPECTED_DOTFILES_COMMIT,
            "Dotfiles producer",
        )
        typed._checkout_head(
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
        for paths in cls.sources.values():
            for source in paths:
                if not source.is_file():
                    raise AssertionError(f"missing canonical expert source: {source}")
        if not cls.android_projection_source.is_file():
            raise AssertionError(
                f"missing Android projection contract: {cls.android_projection_source}"
            )

    def _helper_case(self) -> typed.PrologPythonNimTypedPersistenceE2ETests:
        case = typed.PrologPythonNimTypedPersistenceE2ETests(
            methodName="test_typed_evidence_survives_restart_then_is_fenced_on_project_switch"
        )
        case.dotfiles_root = self.dotfiles_root
        case.zara_core_root = self.zara_core_root
        case.sources = self.sources
        case.android_projection_source = self.android_projection_source
        return case

    def test_canonical_replay_exposes_typed_evidence_without_provider_fallback(self) -> None:
        for name in _PROVIDER_CREDENTIALS:
            self.assertNotIn(name, os.environ)

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        helper = self._helper_case()
        surface_case = helper._surface_case()

        chain_evidence = surface_case._real_chain(root / "expert-state-chain")
        explanations = helper._typed_explanations(
            surface_case,
            root / "expert-state-explain",
        )
        product_provenance = _serialized_product_provenance_refs()
        self.assertEqual(
            set(product_provenance),
            {"zara:expert/prolog", "zara:expert/python", "zara:expert/nim"},
        )
        helper._assert_android_contract()
        typed_evidence = _canonical_typed_evidence(
            chain_evidence,
            explanations,
            product_provenance,
        )

        database_path = root / "conversation.db"
        database = surface.DatabaseManager(database_path)
        store = surface.ConversationStore(database)
        record = store.create_conversation(
            "Canonical typed replay",
            conversation_id="conversation:typed-prolog-python-nim-replay",
        )
        store.save_message(
            surface_case._message(
                record.id,
                1,
                "turn:typed-replay",
                surface.MessageRole.USER,
                "Inspect this project with Prolog, Python, and Nim, then explain why.",
            )
        )
        store.save_message(
            surface_case._message(
                record.id,
                2,
                "turn:typed-replay",
                surface.MessageRole.ASSISTANT,
                "The symbolic language inspection is complete.",
            )
        )
        saved = store.save_symbolic_projection(
            surface.SymbolicConversationProjection(
                conversation_id=record.id,
                projection_generation=1,
                runtime_generation=1,
                turn_id="turn:typed-replay",
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
                    "typed_explanation": True,
                },
                expert_evidence=typed_evidence,
                renderer_provenance=_SYMBOLIC_RENDERER,
                providers_enabled=False,
                max_model_calls=0,
                provider_calls=0,
                model_calls=0,
            ),
            expected_generation=0,
        )
        saved.assert_pure_symbolic()
        database.close()

        reopened_database = surface.DatabaseManager(database_path)
        reopened = surface.ConversationStore(reopened_database)
        recovered = reopened.load_symbolic_projection(record.id)
        self.assertIsNotNone(recovered)
        assert recovered is not None
        recovered.assert_pure_symbolic()

        from zara import __main__ as zara_cli
        from zara.desktop.conversation.replay_status import conversation_symbolic_status

        replay = zara_cli._conversation_replay_payload(reopened, record.id)
        status = conversation_symbolic_status(reopened, record.id)
        projection = replay["symbolic_projection"]
        self.assertIsNotNone(projection)
        assert projection is not None

        self.assertEqual(replay["version"], "ZARA-CONVERSATION-REPLAY/1")
        self.assertEqual(
            [message["content"] for message in replay["messages"]],
            [
                "Inspect this project with Prolog, Python, and Nim, then explain why.",
                "The symbolic language inspection is complete.",
            ],
        )
        self.assertEqual(status["version"], "ZARA-SYMBOLIC-REPLAY/1")
        self.assertEqual(status["symbolic_projection"], projection)
        self.assertEqual(projection["expert_evidence"], typed_evidence)
        self.assertEqual(projection["renderer_provenance"], _SYMBOLIC_RENDERER)
        self.assertIs(projection["providers_enabled"], False)
        self.assertEqual(projection["max_model_calls"], 0)
        self.assertEqual(projection["provider_calls"], 0)
        self.assertEqual(projection["model_calls"], 0)

        for entry in projection["expert_evidence"]:
            self.assertEqual(
                set(entry["explanation"]),
                {"symbolic_terms", "trace"},
            )
            self.assertTrue(entry["explanation"]["symbolic_terms"])
            self.assertTrue(entry["explanation"]["trace"])
            self.assertNotIn("result", entry)
            self.assertEqual(entry["model_calls"], 0)
            provenance = [
                ref
                for ref in entry["evidence_refs"]
                if ref.startswith(_PROVENANCE_PREFIX)
            ]
            self.assertEqual(provenance, [product_provenance[entry["expert_id"]]])

        android = typed._android_twin(recovered)
        self.assertEqual(json.loads(android["expertEvidenceJson"]), projection["expert_evidence"])
        self.assertIs(android["providersEnabled"], projection["providers_enabled"])
        self.assertEqual(android["maxModelCalls"], projection["max_model_calls"])
        self.assertEqual(android["providerCalls"], projection["provider_calls"])
        self.assertEqual(android["modelCalls"], projection["model_calls"])
        self.assertEqual(android["rendererProvenance"], projection["renderer_provenance"])
        android_evidence = json.loads(android["expertEvidenceJson"])
        for entry in android_evidence:
            provenance = [
                ref
                for ref in entry["evidence_refs"]
                if ref.startswith(_PROVENANCE_PREFIX)
            ]
            self.assertEqual(provenance, [product_provenance[entry["expert_id"]]])
        reopened_database.close()


if __name__ == "__main__":
    unittest.main()