"""RED gate: persisted lane-3 expert evidence must not regain provider trust."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any


ZARA_CORE_ROOT = os.environ.get("ZARA_CORE_ROOT")
EXPECTED_ZARA_CORE_COMMIT = "4a7ad7673910e901a09a9e79c81e60bd2aeed8aa"
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
_SYMBOLIC_RENDERER = "symbolic-dcg/v1"
_CONVERSATION_ID = "conversation:lane3-persisted-usage-fence"

if ZARA_CORE_ROOT:
    sys.path.insert(0, str(Path(ZARA_CORE_ROOT).resolve()))

    from zara.principals import PrincipalContext

    server_facade = types.ModuleType("zara.server")
    server_facade.PrincipalContext = PrincipalContext
    sys.modules["zara.server"] = server_facade

    from zara.database import DatabaseManager
    from zara.desktop.conversation import ConversationStore, SymbolicConversationProjection


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


def _canonical_lane3_evidence(expert_id: str) -> dict[str, Any]:
    suffix = expert_id.rsplit("/", 1)[-1]
    return {
        "expert_id": expert_id,
        "invocation_id": f"invocation:{suffix}:persisted-usage-fence",
        "evidence_refs": [f"evidence:language:sha256:{suffix}-trusted"],
        "verdict": "succeeded",
        "model_calls": 0,
        "explanation": {
            "symbolic_terms": [f"decision({suffix},symbolic)."],
            "trace": [f"rule({suffix},symbolic)."],
        },
    }


def _projection(expert_evidence: list[dict[str, Any]]) -> Any:
    return SymbolicConversationProjection(
        conversation_id=_CONVERSATION_ID,
        projection_generation=1,
        runtime_generation=1,
        turn_id="turn:lane3-persisted-usage-fence",
        outcome="success",
        project_id="workspace:lane3-persisted-usage-fence",
        project_generation=1,
        dialogue_act="expert.answer",
        dialogue_state={"selected_experts": ["prolog", "python", "nim"]},
        expert_evidence=expert_evidence,
        renderer_provenance=_SYMBOLIC_RENDERER,
        providers_enabled=False,
        max_model_calls=0,
        provider_calls=0,
        model_calls=0,
    )


@unittest.skipUnless(ZARA_CORE_ROOT, "exact Zara Core checkout not provided")
class PrologPythonNimPersistedUsageFenceE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.zara_core_root = Path(ZARA_CORE_ROOT).resolve()
        _checkout_head(cls.zara_core_root, EXPECTED_ZARA_CORE_COMMIT, "Zara Core")

    def setUp(self) -> None:
        for name in _PROVIDER_CREDENTIALS:
            self.assertNotIn(name, os.environ)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database_path = Path(self.temporary.name) / "conversation.db"
        self.database = DatabaseManager(self.database_path)
        self.store = ConversationStore(self.database)
        self.store.create_conversation(
            "Lane 3 persisted usage fence",
            conversation_id=_CONVERSATION_ID,
        )

    def tearDown(self) -> None:
        self.database.close()

    def test_provider_shaped_lane3_metadata_is_rejected_before_persistence(self) -> None:
        for expert_id in (
            "zara:expert/prolog",
            "zara:expert/python",
            "zara:expert/nim",
        ):
            with self.subTest(expert_id=expert_id):
                evidence = _canonical_lane3_evidence(expert_id)
                evidence["usage"] = {
                    "model_calls": 0,
                    "provider_calls": 1,
                    "provider": "legacy-provider",
                }
                with self.assertRaisesRegex(
                    (TypeError, ValueError),
                    "expert.*(?:usage|provider)|provider.*expert",
                ):
                    _projection([evidence]).validate()

    def test_case_folded_model_calls_metadata_is_rejected_before_persistence(self) -> None:
        for expert_id in (
            "zara:expert/prolog",
            "zara:expert/python",
            "zara:expert/nim",
        ):
            for key_path in ("root", "nested"):
                with self.subTest(expert_id=expert_id, key_path=key_path):
                    evidence = _canonical_lane3_evidence(expert_id)
                    if key_path == "root":
                        evidence["MODEL_CALLS"] = 7
                    else:
                        evidence["explanation"]["MoDeL_CaLlS"] = 7
                    with self.assertRaisesRegex(
                        (TypeError, ValueError),
                        "expert.*model|model.*expert",
                    ):
                        _projection([evidence]).validate()

    def test_legacy_provider_metadata_is_rejected_after_process_recreation(self) -> None:
        canonical = [
            _canonical_lane3_evidence(expert_id)
            for expert_id in (
                "zara:expert/prolog",
                "zara:expert/python",
                "zara:expert/nim",
            )
        ]
        stored = self.store.save_symbolic_projection(
            _projection(canonical),
            expected_generation=0,
        )
        stored.assert_pure_symbolic()
        self.assertEqual(stored.expert_evidence, canonical)

        poisoned = json.loads(json.dumps(canonical))
        poisoned[0]["provider_calls"] = 1
        poisoned[0]["usage"] = {"model_calls": 0, "provider_calls": 1}
        with self.database.transaction(immediate=True) as conn:
            conn.execute(
                """
                UPDATE desktop_symbolic_projections
                SET expert_evidence_json = ?
                WHERE conversation_id = ?
                """,
                (
                    json.dumps(
                        poisoned,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ),
                    _CONVERSATION_ID,
                ),
            )

        self.database.close()
        self.database = DatabaseManager(self.database_path)
        self.store = ConversationStore(self.database)
        with self.assertRaisesRegex(
            (TypeError, ValueError),
            "stored.*expert|expert.*(?:usage|provider)|provider.*expert",
        ):
            self.store.load_symbolic_projection(_CONVERSATION_ID)

    def test_canonical_lane3_evidence_remains_zero_model_after_restart(self) -> None:
        canonical = [
            _canonical_lane3_evidence(expert_id)
            for expert_id in (
                "zara:expert/prolog",
                "zara:expert/python",
                "zara:expert/nim",
            )
        ]
        self.store.save_symbolic_projection(_projection(canonical), expected_generation=0)
        self.database.close()
        self.database = DatabaseManager(self.database_path)
        self.store = ConversationStore(self.database)

        recovered = self.store.load_symbolic_projection(_CONVERSATION_ID)
        self.assertIsNotNone(recovered)
        assert recovered is not None
        recovered.assert_pure_symbolic()
        self.assertEqual(recovered.expert_evidence, canonical)
        self.assertFalse(recovered.providers_enabled)
        self.assertEqual(recovered.max_model_calls, 0)
        self.assertEqual(recovered.provider_calls, 0)
        self.assertEqual(recovered.model_calls, 0)
        for item in recovered.expert_evidence:
            self.assertEqual(item["model_calls"], 0)
            self.assertNotIn("usage", item)
            self.assertNotIn("provider", item)
            self.assertNotIn("provider_calls", item)


if __name__ == "__main__":
    unittest.main()
